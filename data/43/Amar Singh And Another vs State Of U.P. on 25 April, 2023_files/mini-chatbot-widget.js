/**
 * Mini Chatbot Widget for Indian Kanoon Document Pages
 * Clean implementation following DRY, KISS, SOLID principles
 */

// ===== STATE =====
let widgetState = {
    isOpen: false,
    sessionId: null,
    isInitialized: false,
    isResizing: false,
    isArchived: false,
    availableSessions: [],
    userHasScrolledUp: false,  // Track if user manually scrolled away from bottom
    isDraftProcessing: false,  // Track draft creation state
    isCloneProcessing: false   // Track session cloning state
};

let widgetElements = {};
let documentContext = null;

// ===== CONFIGURATION =====
const CONFIG = {
    API_BASE_URL: window.CHATBOT_API_URL || '/prism/api/v1/ik-mini-chat',
    SESSIONS_URL: '/prism/sessions/',
    CLONE_SESSION_URL: '/prism/api/chat/clone-session/',
    GENERATE_DOCUMENT_URL: '/prism/generate-document/',
    SUGGESTIONS: ["What is this doc about?", "Summarize the key points"]
};

// Styles moved to external CSS file (mini-chatbot.css) as per Separation of Concerns

// ===== UTILITIES =====
const UrlBuilder = {
    getCurrentPath() {
        return window.location.pathname + window.location.search + window.location.hash;
    },

    buildAuthUrl(path) {
        return `/${path}/?nextpage=${encodeURIComponent(this.getCurrentPath())}`;
    },

    get loginUrl() { return this.buildAuthUrl('members/login'); },
    get signupUrl() { return this.buildAuthUrl('members/signup'); }
};

const SessionParser = {
    getIdFromUrl() {
        try {
            const hash = window.location.hash.substring(1);
            const params = new URLSearchParams(hash);
            return params.get('session_id');
        } catch (e) {
            return null;
        }
    },

    isOpenRequested() {
        const hash = (window.location.hash || '').toLowerCase();
        return hash.includes('open_chat=1') || hash.includes('open_chat=true');
    }
};

// ===== CSRF TOKEN HANDLING =====
// Matches logic from /static/chat/js/modules/shared/csrf.js
function getCookie(name) {
    if (!document.cookie || document.cookie === '') {
        return null;
    }
    const cookies = document.cookie.split(';');
    for (let i = 0; i < cookies.length; i++) {
        const cookie = cookies[i].trim();
        if (cookie.substring(0, name.length + 1) === (name + '=')) {
            return decodeURIComponent(cookie.substring(name.length + 1));
        }
    }
    return null;
}

function getCSRFToken() {
    // Try to get from form input
    const tokenInput = document.querySelector('[name=csrfmiddlewaretoken]');
    if (tokenInput?.value) {
        return tokenInput.value;
    }
    // Try to get from meta tag
    const metaToken = document.querySelector('meta[name="csrf-token"]');
    if (metaToken?.getAttribute('content')) {
        return metaToken.getAttribute('content');
    }
    // Try to get from cookie
    const cookieToken = getCookie('csrftoken');
    if (cookieToken) {
        return cookieToken;
    }
    return null;
}

// Error message helper (DRY principle)
function handleNetworkError(error, defaultMessage) {
    const lowerMsg = (error?.message || '').toLowerCase();

    if (lowerMsg.includes('credentials') || lowerMsg.includes('authentication') || lowerMsg.includes('unauthorized')) {
        return `Please <a href="${UrlBuilder.loginUrl}" class="chat-link chat-link-blue">login</a> or <a href="${UrlBuilder.signupUrl}" class="chat-link chat-link-green">sign up</a> to use this feature.`;
    }
    if (lowerMsg.includes('network') || lowerMsg.includes('fetch')) {
        return 'Network error occurred. Please check your connection and try again.';
    }
    if (lowerMsg.includes('timeout') || lowerMsg.includes('timed out')) {
        return 'Request timed out. Please try again.';
    }
    if (lowerMsg.includes('session') && (lowerMsg.includes('expired') || lowerMsg.includes('invalid'))) {
        return 'Chat session expired. Please refresh the page to start a new conversation.';
    }
    if (lowerMsg.includes('quota') || lowerMsg.includes('limit')) {
        return 'You\'ve reached your query limit. Please <a href="/prism/pricing/" class="chat-link chat-link-blue">upgrade your plan</a> to continue.';
    }

    return error?.message || defaultMessage;
}

function isAuthenticated() {
    // Only check window.is_auth - CSRF tokens and session cookies can exist for unauthenticated users
    return window.is_auth === true || window.is_auth === 'True';
}

// ===== DOCUMENT CONTEXT =====
function extractDocumentContext() {
    const match = window.location.pathname.match(/\/(doc|docfragment)\/(\d+)\//);
    const indianKanoonMatch = window.location.pathname.match(/\/indiankanoon\/document\/(\d+)\//);

    // Prioritize window.documentContext.title (set by template) over DOM lookup
    // because on mobile, the .doc_title class may contain "Cites/Cited by" text
    let title = window.documentContext?.title;

    // Decode HTML entities (like &amp;) if present in the title from server
    if (title) {
        const tempEl = document.createElement('textarea');
        tempEl.innerHTML = title;
        title = tempEl.value;
    }

    if (!title) {
        const titleElement = document.querySelector('.docfragment_title, .docsource_main');
        title = titleElement?.textContent?.trim() || 'Legal Document';
    }

    documentContext = {
        tid: match ? parseInt(match[2]) : (indianKanoonMatch ? parseInt(indianKanoonMatch[1]) : window.documentContext?.tid || null),
        title: title,
        doctype: window.location.pathname.includes('/doc/') ? 'judgment' : 'document'
    };
}

// ===== UI HELPERS (DRY) =====
const ScrollHelper = {
    THRESHOLD: 50,
    SCROLL_DELAY: 50,

    isAtBottom(messagesEl, threshold = this.THRESHOLD) {
        if (!messagesEl) return true;
        const scrollPosition = messagesEl.scrollTop + messagesEl.clientHeight;
        const scrollHeight = messagesEl.scrollHeight;
        return scrollHeight - scrollPosition <= threshold;
    },

    scrollToBottom(messagesEl, force = false) {
        if (!messagesEl) return;
        if (force || !widgetState.userHasScrolledUp) {
            setTimeout(() => {
                messagesEl.scrollTop = messagesEl.scrollHeight;
            }, this.SCROLL_DELAY);
        }
    },

    resetScrollFlag() {
        widgetState.userHasScrolledUp = false;
    }
};

function isScrolledToBottom(threshold = 50) {
    return ScrollHelper.isAtBottom(widgetElements.messages, threshold);
}

function smartScrollToBottom() {
    ScrollHelper.scrollToBottom(widgetElements.messages, false);
}

function forceScrollToBottom() {
    ScrollHelper.resetScrollFlag();
    ScrollHelper.scrollToBottom(widgetElements.messages, true);
}

function setupScrollListener() {
    if (!widgetElements.messages) return;

    widgetElements.messages.addEventListener('scroll', () => {
        widgetState.userHasScrolledUp = !isScrolledToBottom();
    });
}

function updateUrlHash(sessionId) {
    const hash = sessionId ? `#open_chat=1&session_id=${sessionId}` : '#open_chat=1';
    window.history.replaceState(null, null, window.location.pathname + window.location.search + hash);
}

function hideWidget() {
    if (widgetElements.widget) {
        widgetElements.widget.style.display = 'none';
        widgetElements.widget.classList.remove('open');
        widgetElements.toggle.classList.remove('hidden');
        widgetState.isOpen = false;
    }
}

function resetWidgetUI() {
    widgetElements.historyDropdown.classList.remove('open');
    widgetElements.messages.innerHTML = '';
    widgetState.sessionId = null;
    widgetElements.widget.classList.add('loading-state');
}

// Helper to prevent URLs from being rendered as code blocks
function preprocessMarkdown(text) {
    if (!text) return '';
    // specific fix for indiankanoon links that get wrapped in backticks
    // Replace `http...` with http...
    return text.replace(/`((?:https?:\/\/|www\.)[^\s`]+)`/g, '$1');
}

// ===== MESSAGE CREATION =====
function createMessage(content, role) {
    const cssRole = role === 'user' ? 'user' : 'bot';
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${cssRole}-message`;

    const messageContent = document.createElement('div');
    messageContent.className = 'message-content';

    if (role === 'user') {
        messageContent.textContent = content;
    } else {
        // Pre-process content to fix link rendering issues
        const processedContent = preprocessMarkdown(content);
        messageContent.innerHTML = window.renderMarkdown(processedContent);
    }

    messageDiv.appendChild(messageContent);
    return messageDiv;
}

function createSystemMessage(content, isError = false) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message system ${isError ? 'error-message' : ''}`;

    const messageContent = document.createElement('div');
    messageContent.className = 'message-content';
    // Use innerHTML for system messages to support links (like login/signup)
    // Use textContent for user/bot messages to prevent XSS
    messageContent.innerHTML = content;

    messageDiv.appendChild(messageContent);
    return messageDiv;
}

function showLoading(message = 'Analyzing your legal query...') {
    hideLoading();
    const loadingDiv = document.createElement('div');
    loadingDiv.className = 'message assistant loading-message';
    loadingDiv.innerHTML = `
        <div class="message-content">
            <div class="loading-indicator">
                <span class="loading-text">${window.escapeHTML(message)}</span>
                <div class="loading-dots">
                    <span></span><span></span><span></span>
                </div>
            </div>
        </div>
    `;
    widgetElements.messages.appendChild(loadingDiv);
}

function hideLoading() {
    widgetElements.messages.querySelectorAll('.loading-message').forEach(el => el.remove());
}

// ===== VIEW RENDERING (SOLID / Composition) =====
function renderWidgetHeader() {
    return `
        <div class="mini-chatbot-header">
            <div class="header-title">
                <img src="/static/chat/images/UploadChat.png" alt="Upload and Chat" loading="lazy" width="20" height="20">
                <span>Talk with IK doc</span>
            </div>
            <div class="header-actions">
                <button id="history-chat" class="header-btn" title="View Chat History" aria-label="View Chat History" style="display: none;">
                     <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                        <path d="M13 3c-4.97 0-9 4.03-9 9H1l3.89 3.89.07.14L9 12H6c0-3.87 3.13-7 7-7s7 3.13 7 7-3.13 7-7 7c-1.93 0-3.68-.79-4.94-2.06l-1.42 1.42C8.27 19.99 10.51 21 13 21c4.97 0 9-4.03 9-9s-4.03-9-9-9zm-1 5v5l4.28 2.54.72-1.21-3.5-2.08V8H12z"/>
                    </svg>
                </button>
                <button id="new-chat" class="header-btn" title="Start New Chat (Clears Current View)" aria-label="Start New Chat">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                        <path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/>
                    </svg>
                </button>
                <button id="minimize-chat" class="header-btn" title="Minimize Chat" aria-label="Minimize Chat">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                        <path d="M19 13H5v-2h14v2z"/>
                    </svg>
                </button>
                <button id="copy-chat" class="header-btn" title="Copy Conversation to Clipboard" aria-label="Copy Conversation">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                        <path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/>
                    </svg>
                </button>
                <button id="archive-chat" class="header-btn" title="Archive this Conversation" aria-label="Archive Chat">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                        <path d="M20 6H4l2 14h12l2-14zm-2 2l-1.5 10h-9L6 8h12zM9 1h6v2H9V1zm-1 4h8v1H8V5z"/>
                    </svg>
                </button>
            </div>
        </div>
    `;
}

function renderSuggestions(authRequired) {
    return `
        <div class="mini-chatbot-suggestions" id="mini-chatbot-suggestions" ${authRequired ? 'style="display: none;"' : ''}>
            ${CONFIG.SUGGESTIONS.map(suggestion =>
        `<button type="button" class="suggestion-chip" data-suggestion="${window.escapeHTML(suggestion)}" aria-label="Ask: ${window.escapeHTML(suggestion)}">${window.escapeHTML(suggestion)}</button>`
    ).join('')}
        </div>
    `;
}

function renderInputArea(title, authRequired) {
    return `
        <div class="mini-chatbot-input ${authRequired ? 'disabled' : ''}">
            <div class="input-container">
                <textarea id="chat-input" placeholder="${authRequired ? 'Please login to start chatting' : 'Ask about this document...'}" rows="1" ${authRequired ? 'disabled' : ''} aria-label="Chat input" ${authRequired ? 'aria-disabled="true"' : ''}></textarea>
                <button id="send-message" class="send-btn" disabled aria-label="Send message">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                        <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/>
                    </svg>
                </button>
            </div>

            <!-- Case Name Row -->
            <div class="input-doc-title-row">
                <small class="doc-title-full" title="${title}">${title}</small>
            </div>

            <!-- Action Buttons Row -->
            <div class="input-actions-row">
                <div class="action-buttons-group">
                    ${!authRequired ? `
                        <button id="draft-btn" class="footer-btn footer-btn--draft"
                                title="Create Draft Document"
                                aria-label="Create Draft Document"
                                data-hover-text="Takes you to Document Generation"
                                disabled>
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                                <path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04c.39-.39.39-1.02 0-1.41l-2.34-2.34c-.39-.39-1.02-.39-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/>
                            </svg>
                            <span>Draft Document</span>
                        </button>
                        <button id="kyk-btn" class="footer-btn footer-btn--kyk"
                                title="Take this chat to Know Your Kanoon"
                                aria-label="Take this chat to Know Your Kanoon"
                                data-hover-text="Takes you to Know Your Kanoon"
                                disabled>
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                                <path d="M19 19H5V5h7V3H5c-1.11 0-2 .9-2 2v14c0 1.1.89 2 2 2h14c1.11 0 2-.9 2-2v-7h-2v7zM14 3v2h3.59l-9.83 9.83 1.41 1.41L19 6.41V10h2V3h-7z"/>
                            </svg>
                            <span>Take this chat to Know Your Kanoon</span>
                        </button>
                    ` : ''}
                </div>
                <small class="powered-by"><a href="/prism/" rel="noopener" target="_blank">Powered by Prism</a></small>
            </div>
        </div>
    `;
}

function createWidget() {
    const title = window.escapeHTML(documentContext.title);
    const authRequired = !isAuthenticated();

    const widgetHtml = `
        <button id="mini-chatbot-toggle" class="mini-chatbot-toggle" title="Talk with IK doc" aria-label="Open chat" aria-expanded="false">
            <div class="toggle-icon-wrapper">
                <img src="/static/chat/images/logo.png" alt="Prism Logo">
                <span class="chat-label">Prism AI - CHAT</span>
            </div>
        </button>

        <div id="mini-chatbot-widget" class="mini-chatbot-widget welcome-mode" style="display: none;" role="dialog" aria-label="Legal document chat assistant">
            ${renderWidgetHeader()}

            <div id="history-dropdown" class="history-dropdown" role="listbox" aria-label="Chat history">
                <!-- Populated by JS -->
            </div>

            <div class="mini-chatbot-messages" id="mini-chatbot-messages">
                ${createWelcomeCard()}
            </div>

            ${renderSuggestions(authRequired)}
            ${renderInputArea(title, authRequired)}
            
            <div class="resize-handle" id="resize-handle"></div>
        </div>
    `;

    document.body.insertAdjacentHTML('beforeend', widgetHtml);

    widgetElements = {
        toggle: document.getElementById('mini-chatbot-toggle'),
        widget: document.getElementById('mini-chatbot-widget'),
        messages: document.getElementById('mini-chatbot-messages'),
        input: document.getElementById('chat-input'),
        sendBtn: document.getElementById('send-message'),
        suggestions: document.getElementById('mini-chatbot-suggestions'),
        resizeHandle: document.getElementById('resize-handle'),
        historyBtn: document.getElementById('history-chat'),
        historyDropdown: document.getElementById('history-dropdown')
    };

    if (!widgetElements.toggle || !widgetElements.widget || !widgetElements.messages ||
        !widgetElements.input || !widgetElements.sendBtn) {
        throw new Error('Failed to create widget elements.');
    }
}

function createWelcomeCard() {
    if (!isAuthenticated()) {
        return `
            <div class="welcome-card login-required" id="welcome-card">
                <div class="welcome-icon">
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor">
                        <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zM13 17h-2v-6h2v6zm0-8h-2V7h2v2z"/>
                    </svg>
                </div>
                <h2>Login Required</h2>
                <p>You need to be signed in to use the AI legal assistant for this ${documentContext.doctype}.</p>
                <div class="login-benefits">
                    <ul class="welcome-tips">
                        <li>Ask questions about the document</li>
                        <li>Get legal explanations and summaries</li>
                        <li>Save your chat history</li>
                    </ul>
                </div>
                <button class="primary-btn" id="login-btn">Login to Chat</button>
                <p class="login-note"><small>New user? <a href="${UrlBuilder.signupUrl}" target="_blank">Sign up here</a></small></p>
            </div>
        `;
    }

    return `
        <div class="welcome-card" id="welcome-card">
            <div class="welcome-icon">
                <svg width="28" height="28" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M20 2H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h4l4 4 4-4h4c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z"/>
                </svg>
            </div>
            <h2>Hi! I'm Prism.</h2>
            <p>Ask me anything about this legal document — I'll help you understand the key points and context.</p>
            <button class="primary-btn" id="start-chat-btn">Start Chat</button>
        </div>
    `;
}

// ===== EVENT BINDING (DRY) =====
const EventBinder = {
    bindClick(id, handler) {
        document.getElementById(id)?.addEventListener('click', handler);
    },

    bindClickAll(selector, handler) {
        document.querySelectorAll(selector).forEach(el => {
            el.addEventListener('click', handler);
        });
    },

    bindKeyboard(selector, keys, handler) {
        document.querySelectorAll(selector).forEach(el => {
            el.addEventListener('keydown', (e) => {
                if (keys.includes(e.key)) {
                    e.preventDefault();
                    handler(e, el);
                }
            });
        });
    }
};

// ===== SVG ICONS =====
const Icons = {
    ARCHIVE: 'M20 6H4l2 14h12l2-14zm-2 2l-1.5 10h-9L6 8h12zM9 1h6v2H9V1zm-1 4h8v1H8V5z',
    UNARCHIVE: 'M20.54 5.23l-1.39-1.68C18.88 3.21 18.47 3 18 3H6c-.47 0-.88.21-1.16.55L3.46 5.23C3.17 5.57 3 6.02 3 6.5V19c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V6.5c0-.48-.17-.93-.46-1.27zM12 17.5L6.5 12H10v-2h4v2h3.5L12 17.5zM5.12 5l.81-1h12l.94 1H5.12z'
};

// ===== DROPDOWN MANAGER =====
const DropdownManager = {
    closeOnClickOutside(event, dropdown, trigger) {
        if (dropdown?.classList.contains('open') &&
            !dropdown.contains(event.target) &&
            event.target !== trigger) {
            dropdown.classList.remove('open');
        }
    },

    toggle(dropdown, onOpenCallback) {
        dropdown.classList.toggle('open');
        if (dropdown.classList.contains('open') && onOpenCallback) {
            onOpenCallback();
        }
    },

    close(dropdown) {
        dropdown?.classList.remove('open');
    }
};

// ===== STORAGE MANAGER =====
const StorageManager = {
    get(key, defaultValue = null) {
        try {
            const item = localStorage.getItem(key);
            return item ? JSON.parse(item) : defaultValue;
        } catch (_) {
            return defaultValue;
        }
    },

    set(key, value) {
        try {
            localStorage.setItem(key, JSON.stringify(value));
            return true;
        } catch (_) {
            return false;
        }
    },

    isValidTimestamp(data, maxAge) {
        return data && data.timestamp && (Date.now() - data.timestamp) <= maxAge;
    }
};

// ===== WIDGET SIZE MANAGER =====
const SizeManager = {
    STORAGE_KEY: 'miniChatbotSize',
    MAX_AGE: 30 * 24 * 60 * 60 * 1000, // 30 days
    LIMITS: { minW: 300, maxW: 600, minH: 400, maxH: 900 },

    save(widget) {
        if (!widget) return;
        const rect = widget.getBoundingClientRect();
        const data = { width: Math.round(rect.width), height: Math.round(rect.height), timestamp: Date.now() };
        StorageManager.set(this.STORAGE_KEY, data);
    },

    restore(widget) {
        if (!widget || window.innerWidth <= 768) return;
        const size = StorageManager.get(this.STORAGE_KEY);
        if (!size || !StorageManager.isValidTimestamp(size, this.MAX_AGE)) return;

        const maxH = Math.min(window.innerHeight * 0.8, this.LIMITS.maxH);
        const width = Math.max(this.LIMITS.minW, Math.min(this.LIMITS.maxW, size.width));
        const height = Math.max(this.LIMITS.minH, Math.min(maxH, size.height));

        widget.style.width = `${width}px`;
        widget.style.height = `${height}px`;
    }
};

function bindEvents() {
    widgetElements.toggle.addEventListener('click', toggleWidget);
    EventBinder.bindClick('copy-chat', copyChat);
    EventBinder.bindClick('new-chat', startNewSession);
    EventBinder.bindClick('minimize-chat', toggleWidget);
    EventBinder.bindClick('archive-chat', toggleArchive);
    EventBinder.bindClick('start-chat-btn', exitWelcomeMode);
    EventBinder.bindClick('login-btn', () => { window.location.href = UrlBuilder.loginUrl; });

    // Draft and KYK button bindings
    EventBinder.bindClick('draft-btn', handleDraftCreation);
    EventBinder.bindClick('kyk-btn', handleCloneToKYK);

    // History Toggle
    widgetElements.historyBtn?.addEventListener('click', (e) => {
        e.stopPropagation();
        toggleHistoryDropdown();
    });

    // Close history on outside click
    document.addEventListener('click', (e) => {
        DropdownManager.closeOnClickOutside(e, widgetElements.historyDropdown, widgetElements.historyBtn);
    });

    widgetElements.input.addEventListener('input', handleInput);
    widgetElements.input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });
    widgetElements.sendBtn.addEventListener('click', sendMessage);

    // Suggestion chips
    EventBinder.bindClickAll('.suggestion-chip', (e) => {
        exitWelcomeMode();
        widgetElements.input.value = e.target.dataset.suggestion;
        handleInput();
        focusInput();
    });

    // Initialize resize interactions
    initializeResize();

    // Setup scroll listener to track user scroll behavior
    setupScrollListener();
}

function handleInput() {
    if (!isAuthenticated()) return;

    const textarea = widgetElements.input;
    textarea.style.height = 'auto';
    textarea.style.height = Math.min(textarea.scrollHeight, 120) + 'px';
    widgetElements.sendBtn.disabled = !textarea.value.trim();
}

// History Functions
function toggleHistoryDropdown() {
    DropdownManager.toggle(widgetElements.historyDropdown, renderHistoryDropdown);
}


function renderHistoryDropdown() {
    const allSessions = (widgetState.availableSessions || []).filter(s => s.message_count > 0);
    const MAX_DISPLAY = 5;
    const sessions = allSessions.slice(0, MAX_DISPLAY);
    const hasMore = allSessions.length > MAX_DISPLAY;

    const sessionListHtml = sessions.length === 0
        ? '<div style="padding: 15px; text-align: center; color: #718096; font-size: 0.8rem;" role="status">No previous chats</div>'
        : sessions.map(session => HistoryItemRenderer.render(session, widgetState.sessionId)).join('');

    const footerHtml = (hasMore || allSessions.length > 0)
        ? `<div class="history-footer">
            <a href="${CONFIG.SESSIONS_URL}" class="view-all-link">
                View all ${allSessions.length} session${allSessions.length !== 1 ? 's' : ''} →
            </a>
        </div>`
        : '';

    widgetElements.historyDropdown.innerHTML = `
        <div class="history-header">
            <span>Chat History</span>
            <button type="button" class="new-chat-btn" id="new-doc-chat" aria-label="Start new chat">New Chat</button>
        </div>
        <div class="history-list" role="listbox">
            ${sessionListHtml}
        </div>
        ${footerHtml}
    `;

    // Bind history item interactions
    HistoryItemRenderer.bindInteractions(widgetElements, switchSession);

    // Bind new chat button
    widgetElements.historyDropdown.querySelector('#new-doc-chat')?.addEventListener('click', startNewSession);
}

// ===== HISTORY ITEM RENDERER =====
const HistoryItemRenderer = {
    render(session, activeSessionId) {
        const isActive = session.id === activeSessionId;
        const date = new Date(session.updated_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
        const archivedBadge = session.is_archived ? '<span class="archived-badge-sm">Archived</span>' : '';

        return `
            <div class="history-item ${isActive ? 'active' : ''}" data-session-id="${session.id}"
                 role="option" aria-selected="${isActive}" tabindex="${isActive ? '0' : '-1'}"
                 style="cursor: pointer;">
                <div class="history-item-title" title="${session.title}">${session.title}</div>
                <div class="history-item-meta">
                    <span>${date} · ${session.message_count} msgs</span>
                    ${archivedBadge}
                </div>
            </div>
        `;
    },

    bindInteractions(elements, switchHandler) {
        elements.historyDropdown.querySelectorAll('.history-item').forEach(item => {
            const handleSelect = () => switchHandler(parseInt(item.dataset.sessionId));
            item.addEventListener('click', handleSelect);
            item.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    handleSelect();
                }
            });
        });
    }
};



async function loadExistingSession(sessionId) {
    if (!isAuthenticated()) {
        throw new Error('Authentication required.');
    }

    const payload = {
        session_id: sessionId,
        tid: documentContext.tid,
        document_title: documentContext.title,
        create_new: false  // Critical: Don't create a new session, just load the existing one
    };

    // Use the existing create-session endpoint which handles both create and load
    const data = await apiRequest('/create-session/', payload);

    const sessionData = data?.data || data;
    widgetState.sessionId = sessionData.session_id;
    widgetState.isArchived = !!sessionData.is_archived;
    widgetState.availableSessions = sessionData.available_sessions || [];

    updateArchivedUI();
    updateArchiveButton();
    updateActionButtonStates();

    widgetElements.historyBtn.style.display = 'flex';

    if (widgetState.sessionId) {
        const conversationHistory = sessionData.conversation_history;
        if (conversationHistory?.length > 0) {
            loadConversationHistory(conversationHistory);
        } else {
            // Session exists but is empty
            widgetElements.messages.innerHTML = createWelcomeCard();
            widgetElements.widget.classList.add('welcome-mode');
            widgetElements.suggestions.style.display = 'flex';
            document.getElementById('start-chat-btn')?.addEventListener('click', exitWelcomeMode);
        }
    }

    DropdownManager.close(widgetElements.historyDropdown);
    return widgetState.sessionId;
}

async function switchSession(sessionId) {
    if (widgetState.sessionId === sessionId) {
        DropdownManager.close(widgetElements.historyDropdown);
        return;
    }

    updateUrlHash(sessionId);
    resetWidgetUI();

    try {
        await loadExistingSession(sessionId);
    } catch (error) {
        showError("Failed to switch session");
    } finally {
        widgetElements.widget.classList.remove('loading-state');
    }
}

async function startNewSession() {
    updateUrlHash(null); // Clear session_id
    resetWidgetUI();

    try {
        // Explicitly pass null to force a new session creation
        // Pass false to createNew to delay creation until user types (Lazy Creation)
        await initializeSession(null, false);
    } catch (error) {
        showError("Failed to start new session");
    } finally {
        widgetElements.widget.classList.remove('loading-state');
    }
}

async function toggleWidget() {
    // Check authentication first
    if (!isAuthenticated()) {
        showSignUpDialog();
        return;
    }

    widgetState.isOpen = !widgetState.isOpen;

    if (widgetState.isOpen) {
        widgetElements.widget.style.display = 'flex';
        widgetElements.widget.classList.add('open');
        widgetElements.toggle.classList.add('hidden');
        widgetElements.toggle.setAttribute('aria-expanded', 'true');
        focusInput();

        if (!widgetState.sessionId) {
            // Do NOT force create on toggle open. Just check for existing.
            await initializeSession(undefined, false);
        }
    } else {
        widgetElements.widget.style.display = 'none';
        widgetElements.widget.classList.remove('open');
        widgetElements.toggle.classList.remove('hidden');
        widgetElements.toggle.setAttribute('aria-expanded', 'false');
        // Return focus to toggle button when closing
        widgetElements.toggle.focus();
    }
}

function focusInput() {
    setTimeout(() => widgetElements.input.focus(), 100);
}

function loadConversationHistory(history) {
    exitWelcomeMode();
    widgetElements.suggestions.style.display = 'none';
    history.forEach(msg => addMessage(msg.content, msg.role));
    forceScrollToBottom();  // Always scroll to bottom when loading history
}

// ===== RESIZING (upper-left handle) =====
function initializeResize() {
    if (!widgetElements.resizeHandle || !widgetElements.widget) return;

    let startX, startY, startWidth, startHeight, startLeft, startTop;

    const startResize = (e) => {
        widgetState.isResizing = true;
        widgetElements.widget.classList.add('resizing');

        const rect = widgetElements.widget.getBoundingClientRect();
        startX = e.clientX;
        startY = e.clientY;
        startWidth = rect.width;
        startHeight = rect.height;
        startLeft = rect.left;
        startTop = rect.top;

        document.addEventListener('mousemove', doResize);
        document.addEventListener('mouseup', stopResize);

        e.preventDefault();
    };

    const doResize = (e) => {
        if (!widgetState.isResizing) return;

        // For top-left handle, invert deltas so dragging up/left increases size
        const deltaX = startX - e.clientX;
        const deltaY = startY - e.clientY;

        const minW = 300;
        const maxW = 600;
        const minH = 400;
        const maxH = Math.min(window.innerHeight * 0.8, 900);

        const newWidth = Math.max(minW, Math.min(maxW, startWidth + deltaX));
        const newHeight = Math.max(minH, Math.min(maxH, startHeight + deltaY));

        // Keep the bottom-right corner visually anchored: adjust left/top
        const widthDelta = newWidth - startWidth;
        const heightDelta = newHeight - startHeight;

        widgetElements.widget.style.width = `${newWidth}px`;
        widgetElements.widget.style.height = `${newHeight}px`;
        widgetElements.widget.style.left = `${startLeft - widthDelta}px`;
        widgetElements.widget.style.top = `${startTop - heightDelta}px`;
        widgetElements.widget.style.right = 'auto';
        widgetElements.widget.style.bottom = 'auto';
    };

    const stopResize = () => {
        widgetState.isResizing = false;
        widgetElements.widget.classList.remove('resizing');
        document.removeEventListener('mousemove', doResize);
        document.removeEventListener('mouseup', stopResize);
        saveSize();
    };

    widgetElements.resizeHandle.addEventListener('mousedown', startResize);
}

function saveSize() {
    SizeManager.save(widgetElements.widget);
}

function restoreSize() {
    SizeManager.restore(widgetElements.widget);
}

async function initializeSession(explicitSessionId, createNew = false, skipWelcomeUI = false) {
    if (!isAuthenticated()) {
        throw new Error('Authentication required.');
    }

    // Prepare payload based on explicitSessionId:
    // - Number: Switch to specific session
    // - null: Force NEW chat
    // - undefined: Auto-detect from URL or find active

    const payload = {
        tid: documentContext.tid,
        document_title: documentContext.title,
        create_new: createNew
    };

    if (explicitSessionId === null) {
        // User explicitly requested NEW chat
        payload.session_id = null;
    } else if (typeof explicitSessionId === 'number') {
        // Switch to specific session
        payload.session_id = explicitSessionId;
    } else {
        // Undefined (Auto-detect) - check URL
        const urlSessionId = SessionParser.getIdFromUrl();
        if (urlSessionId) {
            payload.session_id = parseInt(urlSessionId);
        }
        // If no URL session ID, omit 'session_id' key to let backend find active
    }

    // Pass session_id to backend
    const data = await apiRequest('/create-session/', payload);

    const sessionData = data?.data || data; // Handle both wrapper formats
    widgetState.sessionId = sessionData.session_id; // Can be null now!
    widgetState.isArchived = !!sessionData.is_archived;
    widgetState.availableSessions = sessionData.available_sessions || [];

    // NOTE: Removed "Throw if Session ID not received" check to allow empty state

    updateArchivedUI();
    updateArchiveButton();
    updateActionButtonStates();

    // Always show History Button if we have history or session
    widgetElements.historyBtn.style.display = 'flex';

    if (widgetState.sessionId) {
        const conversationHistory = sessionData.conversation_history;
        if (conversationHistory?.length > 0) {
            loadConversationHistory(conversationHistory);
        } else if (!skipWelcomeUI) {
            // New session created but empty - show welcome card only if not suppressed
            widgetElements.messages.innerHTML = createWelcomeCard();
            widgetElements.widget.classList.add('welcome-mode');
            widgetElements.suggestions.style.display = 'flex';
            document.getElementById('start-chat-btn')?.addEventListener('click', exitWelcomeMode);
        }
    } else if (!skipWelcomeUI) {
        // No active session found. Show Welcome only if not suppressed.
        widgetElements.messages.innerHTML = createWelcomeCard();
        widgetElements.widget.classList.add('welcome-mode');
        widgetElements.suggestions.style.display = 'flex';
        document.getElementById('start-chat-btn')?.addEventListener('click', exitWelcomeMode);
    }

    return widgetState.sessionId;
}

function updateArchivedUI() {
    const existingBanner = widgetElements.widget.querySelector('.archived-banner');
    if (widgetState.isArchived) {
        if (!existingBanner) {
            const banner = document.createElement('div');
            banner.className = 'archived-banner';
            banner.setAttribute('role', 'status');
            banner.setAttribute('aria-live', 'polite');
            banner.innerHTML = `
                <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M20 6H4l2 14h12l2-14zm-2 2l-1.5 10h-9L6 8h12zM9 1h6v2H9V1zm-1 4h8v1H8V5z"/></svg>
                <span>This session is archived. Send a message to restore it.</span>
            `;
            // Insert after header
            const header = widgetElements.widget.querySelector('.mini-chatbot-header');
            header.insertAdjacentElement('afterend', banner);
            widgetElements.widget.classList.add('is-archived');
        }
    } else {
        if (existingBanner) existingBanner.remove();
        widgetElements.widget.classList.remove('is-archived');
    }
}

function updateArchiveButton() {
    const archiveBtn = document.getElementById('archive-chat');
    if (!archiveBtn) return;

    const isArchived = widgetState.isArchived;
    archiveBtn.title = isArchived ? 'Unarchive Chat' : 'Archive Chat';
    archiveBtn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="${isArchived ? Icons.UNARCHIVE : Icons.ARCHIVE}"/></svg>`;
}

async function toggleArchive() {
    if (!widgetState.sessionId) {
        showError('No active session to archive');
        return;
    }

    try {
        // KISS: Direct call, removed redundant wrappers
        await updateSessionArchiveStatus(!widgetState.isArchived);
    } catch (error) {
        const errorMessage = handleNetworkError(error, 'Failed to update session status');
        showError(errorMessage);
    }
}

/**
 * DRY helper for archive/unarchive operations
 * @param {boolean} isArchived - true to archive, false to unarchive
 */
async function updateSessionArchiveStatus(isArchived) {
    const endpoint = isArchived ? '/archive-session/' : '/unarchive-session/';
    const response = await apiRequest(endpoint, {
        session_id: widgetState.sessionId
    });

    if (response.status === 'success') {
        widgetState.isArchived = isArchived;
        updateArchivedUI();
        updateArchiveButton();

        const action = isArchived ? 'archived' : 'restored';
        showMessage(`Session ${action} successfully`, false, true);

        // Update session in available list
        if (widgetState.availableSessions.length > 0) {
            const currentSession = widgetState.availableSessions.find(s => s.id === widgetState.sessionId);
            if (currentSession) {
                currentSession.is_archived = isArchived;
            }
            renderHistoryDropdown();
        }
    }
}

// Redundant wrappers archiveSession/unarchiveSession removed

// ===== ERROR RESPONSE PARSING =====
// Default error messages by status code
function getDefaultErrorMessage(status) {
    if (status === 401 || status === 403) {
        return `Please <a href="${UrlBuilder.loginUrl}" style="color: #3182ce; text-decoration: none;">login</a> or <a href="${UrlBuilder.signupUrl}" style="color: #38a169; text-decoration: none;">sign up</a> to use this feature.`;
    } else if (status === 500) {
        return 'Server error occurred. Please try again later.';
    } else if (status === 503) {
        return 'Service temporarily unavailable. Please try again later.';
    }
    return `Request failed with status ${status}`;
}

// Centralized error parsing helper (matches shared/ApiClient.js pattern)
async function parseErrorResponse(response) {
    let errorMessage = null;
    let errorData = null;

    // Try to extract error message from JSON response
    try {
        errorData = await response.json();
        // Try multiple common error field names
        errorMessage = errorData.message || errorData.error || errorData.detail ||
            errorData.msg || (typeof errorData === 'string' ? errorData : null) ||
            (errorData.errors && typeof errorData.errors === 'string' ? errorData.errors : null);
    } catch {
        // JSON parsing failed, try to get text response
        try {
            const textResponse = await response.text();
            if (textResponse && textResponse.trim()) {
                errorMessage = textResponse;
            }
        } catch {
            // Both JSON and text parsing failed
        }
    }

    return { errorMessage, errorData };
}

// ===== QUOTA ERROR HANDLING =====
async function handleQuotaError(response) {
    let errorData;

    try {
        errorData = await response.json();
    } catch {
        errorData = {};
    }

    const error = new Error('Plan limit exceeded');
    error.response = { status: 402, data: errorData };

    // Use centralized quota error handler if available
    if (window.QuotaErrorHandler) {
        window.QuotaErrorHandler.handle(error);
    } else if (window.quotaAlertHandler) {
        const data = {
            title: errorData.title || 'Plan Exhausted',
            message: errorData.message || 'You have reached your monthly AI query limit.',
            upgrade_url: errorData.upgrade_url || '/prism/pricing/',
            usage_data: errorData.usage_data || {}
        };
        window.quotaAlertHandler.showQuotaExceededAlert(data);
    }

    throw error;
}

async function apiRequest(endpoint, data) {
    if (!isAuthenticated()) {
        throw new Error('Authentication required.');
    }

    const baseUrl = CONFIG.API_BASE_URL.replace(/\/$/, '');
    const endpointPath = endpoint.replace(/^\//, '');
    const url = `${baseUrl}/${endpointPath}`;

    const response = await fetch(url, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCSRFToken(),
            'Accept': 'application/json'
        },
        credentials: 'same-origin',
        body: JSON.stringify(data)
    });

    if (response.status === 401) {
        showSignUpDialog();
        hideWidget();
        throw new Error('Authentication required.');
    }

    if (response.status === 402) {
        return handleQuotaError(response);
    }

    if (!response.ok) {
        // Use centralized error response parser
        const { errorMessage, errorData } = await parseErrorResponse(response);

        // If no message extracted, use defaults based on status code
        const finalMessage = errorMessage || getDefaultErrorMessage(response.status);

        const error = new Error(finalMessage);
        error.status = response.status;
        error.data = errorData;
        throw error;
    }

    return response.json();
}

async function sendMessage() {
    if (!isAuthenticated()) return;

    const message = widgetElements.input.value.trim();
    if (!message) return;

    exitWelcomeMode();

    if (!widgetState.sessionId) {
        try {
            // Force create new session now that user has typed
            // skipWelcomeUI=true because user is already sending a message
            await initializeSession(undefined, true, true);
        } catch (error) {
            const errorMessage = handleNetworkError(error, 'Unable to start chat session. Please refresh and try again.');
            showError(errorMessage);
            return;
        }
    }

    widgetElements.input.value = '';
    handleInput();
    addMessage(message, 'user');
    widgetElements.suggestions.style.display = 'none';
    showLoading('Analyzing document...');

    try {
        const data = await apiRequest('/send-message/', {
            session_id: widgetState.sessionId,
            message: message,
            document_title: documentContext.title
        });

        const responseData = data?.data || data;
        const responseText = responseData.response;

        // Real-time UI Sync: Update archive status from server
        if (typeof responseData.is_archived !== 'undefined') {
            const wasArchived = widgetState.isArchived;
            widgetState.isArchived = responseData.is_archived;

            if (wasArchived !== widgetState.isArchived) {
                updateArchivedUI();
                updateArchiveButton();

                // Update history list in real-time
                if (widgetState.availableSessions.length > 0) {
                    const currentSession = widgetState.availableSessions.find(s => s.id === widgetState.sessionId);
                    if (currentSession) {
                        currentSession.is_archived = widgetState.isArchived;
                    }
                    renderHistoryDropdown();
                }
            }
        }

        if (!responseText) {
            throw new Error('No response received from API.');
        }
        addMessage(responseText, 'bot');
        updateActionButtonStates();
    } catch (error) {
        let errorMessage;

        // If this is an API error (has status code), use the message directly
        // because apiRequest() already extracted the proper error message
        if (error.status) {
            errorMessage = error.message || 'Failed to send message. Please try again.';
        } else {
            // For network-level errors (no status code), use handleNetworkError
            errorMessage = handleNetworkError(error, 'Failed to send message. Please try again.');
        }

        showError(errorMessage);
    } finally {
        hideLoading();
        focusInput();
    }
}

function addMessage(content, type) {
    const messageElement = createMessage(content, type);
    widgetElements.messages.appendChild(messageElement);

    // Force scroll for user messages (they just sent it), smart scroll for bot messages
    if (type === 'user') {
        forceScrollToBottom();
    } else {
        smartScrollToBottom();
    }
}

function showMessage(message, isError = false, isSuccess = false) {
    const element = createSystemMessage(message, isError);
    if (isSuccess) element.classList.add('copy-success-message');
    widgetElements.messages.appendChild(element);
    smartScrollToBottom();
    if (isSuccess) setTimeout(() => element.remove(), 3000);
}

function showError(message) {
    showMessage(message, true);
}

function exitWelcomeMode() {
    widgetElements.widget.classList.remove('welcome-mode');
    document.getElementById('welcome-card')?.remove();
    focusInput();
}

async function copyChat() {
    try {
        const chatText = generateChatText();

        if (!chatText) {
            throw new Error('No chat content to copy.');
        }

        if (!navigator.clipboard?.writeText) {
            throw new Error('Clipboard API not available.');
        }

        await navigator.clipboard.writeText(chatText);
        showMessage('Chat copied to clipboard!', false, true);
    } catch (error) {
        showError(error.message || 'Failed to copy chat to clipboard.');
    }
}

function generateChatText() {
    const messages = widgetElements.messages.querySelectorAll('.message:not(.loading-message):not(.system)');
    if (messages.length === 0) {
        return '';
    }

    const documentTitle = documentContext.title;
    let chatText = `Legal Document Chat: ${documentTitle}\n`;
    chatText += `${'='.repeat(50)}\n\n`;

    messages.forEach((message) => {
        const isUser = message.classList.contains('user');
        const messageContent = message.querySelector('.message-content');

        if (messageContent) {
            const role = isUser ? 'User' : 'Assistant';
            const content = isUser ? messageContent.textContent : extractPlainText(messageContent);
            chatText += `${role}: ${content}\n\n`;
        }
    });

    chatText += `Exported from IK Prism at ${new Date().toLocaleString()}`;
    return chatText;
}

function extractPlainText(element) {
    const tempDiv = document.createElement('div');
    tempDiv.innerHTML = element.innerHTML
        .replace(/<br\s*\/?>/gi, '\n')
        .replace(/<\/p>/gi, '\n\n')
        .replace(/<p[^>]*>/gi, '')
        .replace(/<\/h[1-6]>/gi, '\n')
        .replace(/<h[1-6][^>]*>/gi, '')
        .replace(/<\/li>/gi, '\n')
        .replace(/<li[^>]*>/gi, '• ')
        .replace(/<\/ul>|<\/ol>/gi, '\n')
        .replace(/<ul[^>]*>|<ol[^>]*>/gi, '')
        .replace(/<strong[^>]*>(.*?)<\/strong>/gi, '**$1**')
        .replace(/<em[^>]*>(.*?)<\/em>/gi, '*$1*')
        .replace(/<code[^>]*>(.*?)<\/code>/gi, '`$1`')
        .replace(/<[^>]*>/g, '');

    return (tempDiv.textContent || tempDiv.innerText || '').replace(/\n\s*\n\s*\n/g, '\n\n').trim();
}

// ===== DRAFT AND SESSION CLONING FUNCTIONS =====

/**
 * Utility class for managing button action states (DRY principle)
 * Single Responsibility: Handle button UI state transitions
 */
const ButtonActionHandler = {
    /**
     * Execute an async action with button loading/success/error states
     * @param {Object} config - Configuration object
     * @param {string} config.buttonId - Button element ID
     * @param {string} config.stateKey - Widget state key for tracking processing
     * @param {string} config.loadingText - Text to show during loading
     * @param {string} config.successText - Text to show on success
     * @param {Function} config.action - Async function to execute
     * @param {Function} config.onSuccess - Optional callback after successful action
     */
    async execute({ buttonId, stateKey, loadingText, successText, action, onSuccess }) {
        if (!widgetState.sessionId || widgetState[stateKey]) return;

        const button = document.getElementById(buttonId);
        if (!button) return;

        // Set processing state
        widgetState[stateKey] = true;
        updateActionButtonStates();

        const originalText = button.innerHTML;
        button.innerHTML = `<span class="loading-spinner"></span> ${loadingText}`;
        button.classList.add('processing');

        try {
            const result = await action();

            // Success state
            button.innerHTML = `✓ ${successText}`;

            if (onSuccess) {
                await onSuccess(result);
            }

            // Reset after delay
            setTimeout(() => {
                button.innerHTML = originalText;
                button.classList.remove('processing');
                widgetState[stateKey] = false;
                updateActionButtonStates();
            }, 500);

        } catch (error) {
            // Error state - reset immediately
            button.innerHTML = originalText;
            button.classList.remove('processing');
            widgetState[stateKey] = false;
            updateActionButtonStates();
            showError(error.message || 'Action failed');
        }
    }
};

/**
 * Update the enabled/disabled state of Draft and KYK buttons based on session state
 */
function updateActionButtonStates() {
    const draftBtn = document.getElementById('draft-btn');
    const kykBtn = document.getElementById('kyk-btn');

    if (draftBtn) {
        draftBtn.disabled = !widgetState.sessionId || widgetState.isDraftProcessing;
    }
    if (kykBtn) {
        kykBtn.disabled = !widgetState.sessionId || widgetState.isCloneProcessing;
    }
}

/**
 * Fetch session history from the API using the create-session endpoint
 * @param {number} sessionId - The session ID to fetch history for
 * @returns {Promise<Object>} Object containing messages array
 */
async function fetchSessionHistory(sessionId) {
    const response = await fetch(`${CONFIG.API_BASE_URL}/create-session/`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCSRFToken()
        },
        credentials: 'same-origin',
        body: JSON.stringify({
            session_id: sessionId,
            tid: documentContext.tid,
            document_title: documentContext.title,
            create_new: false
        })
    });

    if (!response.ok) {
        throw new Error('Failed to fetch session history');
    }

    const data = await response.json();
    return {
        messages: data.data?.conversation_history || data.conversation_history || []
    };
}

/**
 * Format conversation history for draft document generation
 * @param {Array} messages - Array of message objects with role and content
 * @returns {string} Formatted conversation text
 */
function formatHistoryForDraft(messages) {
    return messages.map(msg => {
        const role = (msg.role === 'user') ? 'User' : 'Assistant';
        const content = msg.content || msg.message || '';
        return `${role}: ${content}`;
    }).join('\n\n');
}

/**
 * Handle draft creation from current session
 */
async function handleDraftCreation() {
    await ButtonActionHandler.execute({
        buttonId: 'draft-btn',
        stateKey: 'isDraftProcessing',
        loadingText: 'Drafting...',
        successText: 'Opening...',
        action: async () => {
            const history = await fetchSessionHistory(widgetState.sessionId);

            if (!history?.messages?.length) {
                throw new Error('Conversation is empty. Start a conversation first.');
            }

            const draftData = {
                content: formatHistoryForDraft(history.messages),
                sessionId: widgetState.sessionId,
                sessionName: documentContext.title
            };

            sessionStorage.setItem('draft_document_context', JSON.stringify(draftData));
            return draftData;
        },
        onSuccess: () => {
            window.open(CONFIG.GENERATE_DOCUMENT_URL + '?fresh=true', '_blank');
        }
    });
}

/**
 * Handle cloning current session to Know Your Kanoon
 */
async function handleCloneToKYK() {
    await ButtonActionHandler.execute({
        buttonId: 'kyk-btn',
        stateKey: 'isCloneProcessing',
        loadingText: 'Cloning...',
        successText: 'Opening...',
        action: async () => {
            const response = await fetch(CONFIG.CLONE_SESSION_URL, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCSRFToken()
                },
                credentials: 'same-origin',
                body: JSON.stringify({
                    source_session_id: widgetState.sessionId,
                    target_tool: 'know_your_kanoon'
                })
            });

            if (!response.ok) {
                let errorMessage = 'Failed to clone session';
                try {
                    const errorData = await response.json();
                    errorMessage = errorData.error || errorData.message || errorMessage;
                } catch {
                    // Use default message if JSON parsing fails
                }
                throw new Error(errorMessage);
            }

            return await response.json();
        },
        onSuccess: (data) => {
            showMessage('Taking you to Know Your Kanoon...', false, true);
            if (data.data?.session_url) {
                window.open(data.data.session_url, '_blank');
            }
        }
    });
}


function showSignUpDialog() {
    const loginUrl = UrlBuilder.loginUrl;
    const signupUrl = UrlBuilder.signupUrl;

    // Check if existing jQuery dialog should be used for consistency
    if (typeof $ !== 'undefined' && $.fn.dialog) {
        const message = `Please <a href="${loginUrl}" style="color: #3182ce; text-decoration: none;">login</a> or <a href="${signupUrl}" style="color: #38a169; text-decoration: none;">sign up</a> to use this feature.`;
        const dialog = document.createElement('div');
        dialog.className = 'advtext';
        dialog.innerHTML = message;
        $(dialog).dialog({
            title: "Login Required",
            closeText: "",
            width: 500,
            modal: true,
            resizable: false
        });
        return;
    }

    // Fallback to simple native dialog if jQuery not available
    const modal = document.createElement('dialog');
    modal.style.cssText = 'padding: 24px; border-radius: 8px; border: none; max-width: 400px; text-align: center;';
    modal.setAttribute('aria-labelledby', 'dialog-title');
    modal.setAttribute('aria-describedby', 'dialog-desc');

    const headingId = 'dialog-title-' + Date.now();
    const descId = 'dialog-desc-' + Date.now();

    modal.innerHTML = `
        <h2 id="${headingId}" style="margin: 0 0 16px 0;">Login Required</h2>
        <p id="${descId}" style="margin: 0 0 24px 0; color: #666;">Please <a href="${loginUrl}" style="color: #3182ce; text-decoration: none;">login</a> or <a href="${signupUrl}" style="color: #38a169; text-decoration: none;">sign up</a> to use this feature.</p>
        <div style="display: flex; gap: 12px; margin-bottom: 16px;">
            <button type="button" class="dialog-login-btn" style="flex: 1; padding: 12px; background: #3182ce; color: white; border: none; border-radius: 4px; cursor: pointer;">Login</button>
            <button type="button" class="dialog-signup-btn" style="flex: 1; padding: 12px; background: #38a169; color: white; border: none; border-radius: 4px; cursor: pointer;">Sign Up</button>
        </div>
        <button type="button" class="dialog-cancel-btn" style="padding: 8px 16px; background: transparent; border: 1px solid #ddd; border-radius: 4px; cursor: pointer;">Cancel</button>
    `;

    document.body.appendChild(modal);
    modal.showModal();

    // Use addEventListener instead of inline onclick
    modal.querySelector('.dialog-login-btn').addEventListener('click', () => {
        window.location.href = loginUrl;
    });
    modal.querySelector('.dialog-signup-btn').addEventListener('click', () => {
        window.location.href = signupUrl;
    });
    modal.querySelector('.dialog-cancel-btn').addEventListener('click', () => {
        modal.close();
    });

    modal.addEventListener('close', () => {
        document.body.removeChild(modal);
    });
}

// ===== INITIALIZATION =====
function waitForDependencies(maxWait = 5000, interval = 50) {
    return new Promise((resolve, reject) => {
        const startTime = Date.now();
        const checkDependencies = () => {
            if (typeof window.renderMarkdown !== 'undefined' && typeof window.escapeHTML !== 'undefined') {
                resolve();
            } else if (Date.now() - startTime > maxWait) {
                reject(new Error('markdown.js module failed to load within timeout. Ensure markdown.js is loaded as a module before this script.'));
            } else {
                setTimeout(checkDependencies, interval);
            }
        };
        checkDependencies();
    });
}

function init() {
    if (widgetState.isInitialized) return;

    extractDocumentContext();
    createWidget();
    bindEvents();
    restoreSize();
    widgetState.isInitialized = true;

    // Auto-open widget if requested via URL hash
    if (SessionParser.isOpenRequested()) {
        setTimeout(() => {
            if (!widgetState.isOpen) {
                toggleWidget();
            }
        }, 50);
    }
}

// ===== ROUTE MATCHER =====
const RouteMatcher = {
    PATTERNS: [
        /\/(doc|docfragment)\/\d+\//,
        /\/indiankanoon\/document\/\d+\//
    ],

    matches() {
        return this.PATTERNS.some(pattern => pattern.test(window.location.pathname));
    }
};

// Auto-initialize on matching pages after dependencies are loaded
if (RouteMatcher.matches()) {
    waitForDependencies().then(init).catch(error => { throw error; });
}
