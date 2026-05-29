/* AI Mega Bot — Mini App JavaScript */
(function() {
    'use strict';

    // Initialize Telegram WebApp
    const tg = window.Telegram && window.Telegram.WebApp;
    
    if (tg) {
        tg.ready();
        tg.expand();
        tg.setHeaderColor('#0f0f23');
        tg.setBackgroundColor('#0f0f23');
    }

    // Buy plan via deep link to bot
    window.buyPlan = function(tier, period) {
        const botUsername = 'aimega_bot';
        const deepLink = `https://t.me/${botUsername}?start=buy_${tier}_${period}`;
        
        if (tg) {
            // Open in Telegram, then close MiniApp
            tg.openTelegramLink(deepLink);
            setTimeout(function() {
                tg.close();
            }, 500);
        } else {
            // Fallback for browser preview
            window.open(deepLink, '_blank');
        }
    };

    // Haptic feedback on button clicks
    document.addEventListener('click', function(e) {
        if (e.target.classList.contains('btn') && tg) {
            tg.HapticFeedback.impactOccurred('light');
        }
    });

    // Theme sync
    if (tg && tg.themeParams) {
        const theme = tg.themeParams;
        if (theme.bg_color) {
            document.documentElement.style.setProperty('--bg', theme.bg_color);
        }
        if (theme.text_color) {
            document.documentElement.style.setProperty('--text', theme.text_color);
        }
    }

    console.log('AI Mega Bot MiniApp loaded');
})();
