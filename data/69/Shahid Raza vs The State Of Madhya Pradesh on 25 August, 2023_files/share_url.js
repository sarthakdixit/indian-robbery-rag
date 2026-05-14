$(document).ready(function() {
    $('#website_device').button({
        icon: 'ui-icon-alert', 
        classes: {
            'ui-button': 'ui-corner-all'
        }
    });
    if (navigator.share) {
        $('#sharelink').css('display', 'inline');

        $('#sharelink').button({
            icon: 'ui-icon-link', 
            classes: {
                'ui-button': 'ui-corner-all'
            }
        });
	$('#sharelink').on('click', function (e) {
            navigator.share({
                title: document.title,
                url: window.location.href,
            });
        });
    };	
});
