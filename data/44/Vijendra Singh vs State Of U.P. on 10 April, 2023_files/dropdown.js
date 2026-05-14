        $(document).ready(function() {
            const hamburgerIcon = '<line x1="3" y1="6" x2="21" y2="6"></line><line x1="3" y1="12" x2="21" y2="12"></line><line x1="3" y1="18" x2="21" y2="18"></line>';
            const closeIcon = '<line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line>';
            const $menu = $('#mobile-menu');
            const $btn = $('#mobile-menu-btn');

            $btn.on('click', function(e) {
                e.preventDefault();
                const isActive = $menu.toggleClass('active').hasClass('active');
                $btn.find('svg').html(isActive ? closeIcon : hamburgerIcon);
                // Update ARIA attributes for screen readers
                $btn.attr('aria-expanded', isActive);
                $btn.attr('aria-label', isActive ? 'Close mobile menu' : 'Open mobile menu');
                $menu.attr('aria-hidden', !isActive);
            });

            const $premiumMenu = $('#premium-dropdown-menu');
            const $premiumBtn = $('#premium-dropdown-btn');

            function closeMobileMenu() {
                $menu.removeClass('active');
                $btn.find('svg').html(hamburgerIcon);
                // Update ARIA attributes for screen readers
                $btn.attr('aria-expanded', 'false');
                $btn.attr('aria-label', 'Open mobile menu');
                $menu.attr('aria-hidden', 'true');
            }

            $('.mobile-nav-link').on('click', closeMobileMenu);

            // Premium dropdown menu with screen reader support
            const $menuItems = $premiumMenu.find('.premium-dropdown-item');

            function openPremiumMenu() {
                $premiumMenu.addClass('active');
                $premiumBtn.attr('aria-expanded', 'true');
                $premiumMenu.attr('aria-hidden', 'false');
                // Move focus to first menu item for screen readers
                $menuItems.first().focus();
            }

            function closePremiumMenu(returnFocus) {
                $premiumMenu.removeClass('active');
                $premiumBtn.attr('aria-expanded', 'false');
                $premiumMenu.attr('aria-hidden', 'true');
                // Return focus to button if requested
                if (returnFocus) {
                    $premiumBtn.focus();
                }
            }

            if ($premiumBtn.length && $premiumMenu.length) {
                $premiumBtn.on('click', function(e) {
                    e.preventDefault();
                    e.stopPropagation();
                    const isActive = $premiumMenu.hasClass('active');
                    if (isActive) {
                        closePremiumMenu(false);
                    } else {
                        openPremiumMenu();
                    }
                });

                // Keyboard navigation within menu
                $premiumMenu.on('keydown', function(e) {
                    const $currentItem = $(document.activeElement);
                    const currentIndex = $menuItems.index($currentItem);

                    if (e.key === 'ArrowDown') {
                        e.preventDefault();
                        const nextIndex = (currentIndex + 1) % $menuItems.length;
                        $menuItems.eq(nextIndex).focus();
                    } else if (e.key === 'ArrowUp') {
                        e.preventDefault();
                        const prevIndex = currentIndex <= 0 ? $menuItems.length - 1 : currentIndex - 1;
                        $menuItems.eq(prevIndex).focus();
                    } else if (e.key === 'Escape') {
                        e.preventDefault();
                        closePremiumMenu(true);
                    } else if (e.key === 'Tab') {
                        // Close menu on Tab to allow normal tab navigation
                        closePremiumMenu(false);
                    }
                });

                // Also support keyboard on button
                $premiumBtn.on('keydown', function(e) {
                    if (e.key === 'ArrowDown' && !$premiumMenu.hasClass('active')) {
                        e.preventDefault();
                        openPremiumMenu();
                    } else if (e.key === 'Escape' && $premiumMenu.hasClass('active')) {
                        e.preventDefault();
                        closePremiumMenu(true);
                    }
                });

                $menuItems.on('click', function() {
                    closePremiumMenu(false);
                });
            }

            $(document).on('click', function(e) {
                const $target = $(e.target);
                if (!$target.closest('.header-nav, .mobile-menu').length) {
                    closeMobileMenu();
                }
                if ($premiumMenu.length && !$target.closest('.premium-dropdown').length && $premiumMenu.hasClass('active')) {
                    closePremiumMenu(false);
                }
            });

            const currentPath = window.location.pathname;
            $('.nav-link, .mobile-nav-link').each(function() {
                const href = $(this).attr('href');
                if (href === currentPath || (href !== '/' && currentPath.startsWith(href))) {
                    $(this).addClass('active');
                }
            });
        });
