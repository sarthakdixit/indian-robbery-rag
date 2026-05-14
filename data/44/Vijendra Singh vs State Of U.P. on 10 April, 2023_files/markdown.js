/**
 * Markdown Processing Module - SOLID: Single responsibility per class
 * Provides markdown rendering and analysis parsing functionality
 */

// Configuration - convention over configuration
const CONFIG = {
    MARKDOWN_OPTIONS: {
        html: true,
        breaks: true,
        linkify: true,
        typographer: false,
        langPrefix: 'language-'
    },
    SANITIZER_OPTIONS: {
        USE_PROFILES: { html: true },
        ALLOWED_ATTR: ['href', 'target', 'rel', 'class', 'id', 'title', 'colspan', 'rowspan', 'scope', 'style', 'role']
    },
    MAX_LENGTH: 800,
    TABLE_PATTERN: /<table[\s\S]*?<\/table>/gi
};

/**
 * Markdown Renderer - Single Responsibility: Render markdown to HTML
 * Dependency Inversion: Accepts sanitizer as dependency
 */
class MarkdownRenderer {
    constructor(sanitizer) {
        this._instance = null;
        this._sanitizer = sanitizer;
    }

    /**
     * Get or create markdown-it instance
     * @returns {Object} markdown-it instance
     * @private
     */
    _getInstance() {
        if (this._instance) return this._instance;

        if (!window.markdownit) {
            throw new Error('markdown-it library is required but not available');
        }

        this._instance = window.markdownit(CONFIG.MARKDOWN_OPTIONS);
        this._instance.linkify.set({ fuzzyEmail: false });
        return this._instance;
    }

    /**
     * Render markdown to HTML with table preservation
     * @param {string} text - Markdown text
     * @returns {string} HTML
     */
    render(text) {
        if (!text || typeof text !== 'string') return '';

        const tables = this._extractTables(text);
        const textWithPlaceholders = this._replaceTablePlaceholders(text, tables);
        const html = this._getInstance().render(textWithPlaceholders);
        const htmlWithTables = this._restoreTables(html, tables);
        return this._sanitizer.sanitize(htmlWithTables);
    }

    /**
     * Extract tables from text
     * @param {string} text - Text containing tables
     * @returns {Array} Array of table HTML
     * @private
     */
    _extractTables(text) {
        const tables = [];
        text.replace(CONFIG.TABLE_PATTERN, (match) => {
            tables.push(match);
            return '';
        });
        return tables;
    }

    /**
     * Replace tables with placeholders
     * @param {string} text - Text with tables
     * @param {Array} tables - Array of table HTML
     * @returns {string} Text with placeholders
     * @private
     */
    _replaceTablePlaceholders(text, tables) {
        return text.replace(CONFIG.TABLE_PATTERN, () =>
            `TABLE_PLACEHOLDER_${tables.length}__`
        );
    }

    /**
     * Restore tables from placeholders
     * @param {string} html - HTML with placeholders
     * @param {Array} tables - Array of table HTML
     * @returns {string} HTML with tables restored
     * @private
     */
    _restoreTables(html, tables) {
        let finalHtml = html;
        tables.forEach((table, index) => {
            const placeholder = `TABLE_PLACEHOLDER_${index + 1}__`;
            const sanitizedTable = this._sanitizer.sanitize(table);
            finalHtml = finalHtml.replace(placeholder, sanitizedTable);
        });
        return finalHtml;
    }
}

/**
 * HTML Sanitizer - Single Responsibility: Sanitize HTML content
 */
class HTMLSanitizer {
    constructor() {
        this._hooksConfigured = false;
    }

    /**
     * Configure DOMPurify hooks
     * @private
     */
    _configureHooks() {
        if (this._hooksConfigured || !DOMPurify) return;

        DOMPurify.addHook('afterSanitizeAttributes', (node) => {
            if (node.tagName === 'A' && node.hasAttribute('href')) {
                const href = node.getAttribute('href');
                if (href && (href.startsWith('http://') || href.startsWith('https://'))) {
                    node.setAttribute('target', '_blank');
                    node.setAttribute('rel', 'noopener noreferrer');
                }
            }
        });

        DOMPurify.addHook('afterSanitizeElements', (node) => {
            // Enhance tables with accessibility and styling attributes
            if (node.tagName === 'TABLE') {
                if (!node.hasAttribute('role')) {
                    node.setAttribute('role', 'table');
                }
                // Add styling class for consistent table appearance
                if (!node.classList.contains('chat-table')) {
                    node.classList.add('chat-table');
                }
            }
            if (node.tagName === 'A' && node.textContent) {
                node.textContent = TextUtils.removeEmojis(node.textContent);
            }
        });

        this._hooksConfigured = true;
    }

    /**
     * Sanitize HTML content
     * @param {string} html - HTML to sanitize
     * @returns {string} Sanitized HTML
     */
    sanitize(html) {
        if (!html) return '';

        this._configureHooks();
        return DOMPurify.sanitize(html, CONFIG.SANITIZER_OPTIONS);
    }
}

/**
 * Text Utilities - Single Responsibility: Text manipulation utilities
 */
class TextUtils {
    /**
     * Escape HTML characters to prevent XSS
     * @param {string} text - Text to escape
     * @returns {string} HTML-escaped text
     */
    static escapeHTML(text) {
        const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#x27;' };
        return text.replace(/[&<>"']/g, (m) => map[m]);
    }

    /**
     * Strip HTML tags from text
     * @param {string} html - HTML content
     * @returns {string} Plain text
     */
    static stripHTML(html) {
        const doc = new DOMParser().parseFromString(html, 'text/html');
        return doc.body.textContent || '';
    }

    /**
     * Count words in text
     * @param {string} text - Text to analyze
     * @returns {number} Word count
     */
    static countWords(text) {
        if (!text) return 0;
        return this.stripHTML(text).trim().split(/\s+/).filter(word => word.length > 0).length;
    }

    /**
     * Remove emojis from text
     * @param {string} text - Text to process
     * @returns {string} Text without emojis
     */
    static removeEmojis(text) {
        return typeof text === 'string'
            ? text.replace(/[\u{1F300}-\u{1F9FF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}\u{1F600}-\u{1F64F}\u{1F680}-\u{1F6FF}\u{1F1E0}-\u{1F1FF}\u{1F900}-\u{1F9FF}\u{1FA00}-\u{1FAFF}]/gu, '').trim()
            : text;
    }
}

/**
 * Analysis Parser - Single Responsibility: Parse legal analysis responses
 * Dependency Inversion: Accepts renderer as dependency
 */
class AnalysisParser {
    static SECTION_PATTERNS = {
        summary: /^(?:[#\s]*)?(summary|overview|document\s+summary|executive\s+summary)/i,
        issues: /^(?:[#\s]*)?(legal\s+issues?|issues?|concerns?|problems?|risks?)/i,
        suggestions: /^(?:[#\s]*)?(recommendations?|suggestions?|advice|improvements?)/i
    };

    constructor(renderer) {
        this._renderer = renderer;
    }

    /**
     * Extract sections from analysis text
     * @param {string} text - Analysis text
     * @returns {Array} Array of sections
     */
    extractSections(text) {
        const lines = text.split('\n');
        let currentSection = null;
        const sections = [];
        let introContent = [];

        for (const line of lines) {
            const trimmedLine = line.trim();

            if (!trimmedLine) {
                if (currentSection?.content.length) currentSection.content.push('');
                else if (introContent.length) introContent.push('');
                continue;
            }

            const matchedSection = this._findSectionType(trimmedLine);

            if (matchedSection) {
                if (currentSection?.content.length) sections.push(currentSection);
                currentSection = { type: matchedSection, title: trimmedLine, content: [] };
            } else {
                if (currentSection) currentSection.content.push(line);
                else introContent.push(line);
            }
        }

        if (currentSection?.content.length) sections.push(currentSection);

        if (introContent.length && !sections.length) {
            sections.push({ type: 'summary', title: 'Analysis', content: introContent });
        }

        return sections;
    }

    /**
     * Find section type from line
     * @param {string} line - Line to analyze
     * @returns {string|null} Section type
     * @private
     */
    _findSectionType(line) {
        if (line.length >= 100) return null;

        for (const [sectionType, pattern] of Object.entries(AnalysisParser.SECTION_PATTERNS)) {
            if (pattern.test(line)) {
                return sectionType;
            }
        }
        return null;
    }

    /**
     * Create default analysis result
     * @param {string} fallbackText - Fallback text
     * @returns {Object} Default result
     */
    createDefaultResult(fallbackText = 'No analysis data available') {
        return {
            summary: fallbackText,
            issues: 'No issues identified.',
            suggestions: 'No suggestions available.',
            raw_sections: []
        };
    }

    /**
     * Parse analysis response into structured result
     * @param {string} text - Analysis text
     * @returns {Object} Parsed result
     */
    parseResponse(text) {
        if (!text || typeof text !== 'string') {
            return this.createDefaultResult(text ? String(text) : undefined);
        }

        const sections = this.extractSections(text);
        const result = { summary: '', issues: '', suggestions: '', raw_sections: [] };

        for (const section of sections) {
            const content = section.content.join('\n').trim();
            if (!content) continue;

            const processedContent = this._renderer.render(content);

            this._assignSection(result, section, processedContent);
            result.raw_sections.push({
                title: section.title || section.type.charAt(0).toUpperCase() + section.type.slice(1),
                content: processedContent,
                type: section.type
            });
        }

        this._ensureDefaults(result, text);
        return result;
    }

    /**
     * Assign section to result
     * @param {Object} result - Result object
     * @param {Object} section - Section object
     * @param {string} processedContent - Processed content
     * @private
     */
    _assignSection(result, section, processedContent) {
        if (section.type === 'summary' && !result.summary) result.summary = processedContent;
        else if (section.type === 'issues' && !result.issues) result.issues = processedContent;
        else if (section.type === 'suggestions' && !result.suggestions) result.suggestions = processedContent;
    }

    /**
     * Ensure result has default values
     * @param {Object} result - Result object
     * @param {string} originalText - Original text
     * @private
     */
    _ensureDefaults(result, originalText) {
        if (!result.raw_sections.length) {
            result.summary = this._renderer.render(originalText);
            result.raw_sections.push({ title: 'Analysis', content: result.summary, type: 'summary' });
        }

        result.summary ||= 'Summary not available.';
        result.issues ||= 'No issues identified.';
        result.suggestions ||= 'No suggestions available.';
    }
}

/**
 * Content Truncator - Single Responsibility: Handle content truncation
 */
class ContentTruncator {
    /**
     * Find break point in content
     * @param {string} content - Content to analyze
     * @param {number} maxLength - Maximum length
     * @returns {number} Break point position
     * @private
     */
    static findBreakPoint(content, maxLength) {
        if (!content || maxLength <= 0) return 0;
        if (content.length <= maxLength) return content.length;

        const sentenceEnd = content.lastIndexOf('. ', maxLength);
        if (sentenceEnd !== -1) return sentenceEnd + 2;

        const spaceIndex = content.lastIndexOf(' ', maxLength);
        return spaceIndex !== -1 ? spaceIndex : maxLength;
    }

    /**
     * Truncate content to specified length
     * @param {string} content - Content to truncate
     * @param {number} maxLength - Maximum length
     * @returns {Object} Truncation result
     */
    static truncate(content, maxLength = CONFIG.MAX_LENGTH) {
        const full = content || '';

        if (!content || typeof content !== 'string' || content.length <= maxLength) {
            return { truncated: full, hasMore: false, full };
        }

        const breakPoint = this.findBreakPoint(content, maxLength);
        return {
            truncated: content.substring(0, breakPoint).trim(),
            hasMore: true,
            full
        };
    }
}

// Singleton instances - DRY: Single instance per class
const sanitizer = new HTMLSanitizer();
const renderer = new MarkdownRenderer(sanitizer);
const analysisParser = new AnalysisParser(renderer);

// Public API
export function renderMarkdown(text) {
    return renderer.render(text);
}

export function parseAnalysisResponse(text) {
    return analysisParser.parseResponse(text);
}

export function truncateContent(content, maxLength) {
    return ContentTruncator.truncate(content, maxLength);
}

export { TextUtils };

// Legacy exports for backward compatibility
export const escapeHTML = TextUtils.escapeHTML;
export const stripHTML = TextUtils.stripHTML;
export const sanitizeHTML = (html) => sanitizer.sanitize(html);

// Global access for legacy code
if (typeof window !== 'undefined') {
    window.renderMarkdown = renderMarkdown;
    window.escapeHTML = escapeHTML;
    window.TextUtils = TextUtils;
}
