$(document).ready(function () {
        var palette = {'Facts': '#FFEC94', 'Issue': '#FFAEAE', 'PetArg': '#CCFFBB', 'RespArg':'#CCCC99', 'Section': '#56BAEC', 'Precedent': '#B4D8E7', 'CDiscource': '#FCE6E6', 'Conclusion': '#C0BCB6'};
        var titledict = {'Facts': 'Fact', 'Issue': 'Issue', 'PetArg': 'Petitioner\'s Argument', 'RespArg':'Respondent\'s Argument', 'Section': 'Analysis of the law', 'Precedent': 'Precedent Analysis', 'CDiscource': 'Court\'s Reasoning', 'Conclusion': 'Conclusion'};
        var button_names = {'Facts': 'Facts', 'Issue': 'Issues', 'PetArg': 'Petitioner\'s Arguments', 'RespArg':'Respondent\'s Arguments', 'Section': 'Analysis of the law', 'Precedent': 'Precedent Analysis', 'CDiscource': 'Court\'s Reasoning', 'Conclusion': 'Conclusion'};
        var sentimentLabels = {'Pos': 'Accepted by Court', 'Neg': 'Negatively Viewed by Court', 'PARTY': 'Relied by Party', 'Neutral': 'No clear sentiment'};
        var sentimentColors = {'Pos': 'green', 'Neg': 'red', 'Neutral': 'yellow', 'PARTY': 'blue'};
        var sentimentNames = ['PARTY', 'Pos', 'Neg', 'Neutral'];
        var structNames = ['Facts', 'Issue', 'PetArg', 'RespArg', 'Section', 'Precedent', 'CDiscource', 'Conclusion'];
        var cssClear = {'text-decoration': '', 'text-decoration-color': '', 'text-decoration-style': ''};

        function initBlogButton(selector) {
            $(selector).button({icon: 'ui-icon-info', text: false});
        }

        function toggleButtonSelection(button) {
            button.attr('data-selected', button.attr('data-selected') !== 'true');
            button.trigger('change');
        }

        function getSelectedValues(buttonName) {
            var parts = [];
            $("button[name='" + buttonName + "']").each(function() {
                if ($(this).attr('data-selected') === 'true') {
                    parts.push($(this).attr('value'));
                }
            });
            return parts;
        }

        
        function updateLabelColors(unmarkId, markId, checked) {
            var activeColor = '#2196F3';
            var inactiveColor = '#999';
            $('#' + unmarkId).css('color', checked ? inactiveColor : activeColor);
            $('#' + markId).css('color', checked ? activeColor : inactiveColor);
        }

        function createButtonRow(buttons, cols) {
            var rows = [];
            for (var i = 0; i < buttons.length; i += cols) {
                rows.push('<tr class="butset">' + buttons.slice(i, i + cols).join('\n') + '</tr>');
            }
            return rows.join('');
        }

        function createToggleSwitch(title, switchId, unmarkId, markId, marginBottom) {
            return '<div style="margin: 12px 0;">' +
                '<div style="font-weight: 600; margin-bottom: ' + (marginBottom || '10px') + '; text-align: center; color: #2c3e50; font-size: 0.95em; letter-spacing: 0.3px;">' + title + '</div>' +
                '<div style="display: flex; align-items: center; justify-content: center; gap: 14px;">' +
                '<span id="' + unmarkId + '" class="toggle-label" style="font-weight: 500; color: #2196F3; transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1); line-height: 28px; display: flex; align-items: center; cursor: pointer; font-size: 0.9em; user-select: none;">Unmark</span>' +
                '<label class="switch" style="position: relative; display: inline-block; width: 52px; height: 28px; margin: 0; vertical-align: middle; cursor: pointer;">' +
                '<input type="checkbox" id="' + switchId + '" name="' + switchId + '" style="opacity: 0; width: 0; height: 0;">' +
                '<span class="slider" style="position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0; background-color: #e0e0e0; transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1); border-radius: 28px; box-shadow: inset 0 2px 4px rgba(0,0,0,0.1);"></span>' +
                '</label>' +
                '<span id="' + markId + '" class="toggle-label" style="font-weight: 500; color: #9e9e9e; transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1); line-height: 28px; display: flex; align-items: center; cursor: pointer; font-size: 0.9em; user-select: none;">Mark</span>' +
                '</div>' +
                '</div>';
        }

        function createButtonHtml(buttonId, className, name, value, label, styleAttr) {
            return '<td class="' + className + '"' + (styleAttr ? ' style="' + styleAttr + '"' : '') + '>' +
                '<input type="checkbox" id="' + buttonId + '_input" name="' + name + '" value="' + value + '" style="display:none;">' +
                '<button id="' + buttonId + '" type="button" class="' + className.replace('chk', 'button') + '" name="' + name + '_button" value="' + value + '" data-selected="false" data-input-id="' + buttonId + '_input">' +
                label + '</button></td>';
        }

        function createFieldset(legendText, blogUrl, blogId, content) {
            return '<fieldset>\n <legend>\n    <span>' + legendText + '</span>\n    <a target="_blank" href="' + blogUrl + '" id="' + blogId + '" class="bloglink" title="Learn how it works!"></a>\n </legend>\n' + content + '\n</fieldset>';
        }

        function createButtonStyles(baseClass, overlayColor, hoverOverlay) {
            return baseClass + ' { ' +
                'width: 100%; padding: 12px 18px; border-radius: 10px; ' +
                'cursor: pointer; font-weight: 600; font-size: 1.2rem; line-height: 1.45; text-align: left; ' +
                'color: #1a1a1a; outline: none; user-select: none; ' +
                'transition: transform 0.2s ease-out, box-shadow 0.2s ease-out; ' +
                'box-shadow: 0 2px 4px rgba(0,0,0,0.1); position: relative; z-index: 1; ' +
            '} ' +
            baseClass + '::before { ' +
                'content: ""; position: absolute; top: 0; left: 0; right: 0; bottom: 0; ' +
                'background-color: ' + overlayColor + '; border-radius: 4px; ' +
                'pointer-events: none; transition: background-color 0.2s ease-out; z-index: -1; ' +
            '} ' +
            baseClass + ':hover { transform: translateY(-1px); box-shadow: 0 3px 6px rgba(0,0,0,0.12); } ' +
            baseClass + ':hover::before { background-color: ' + hoverOverlay + '; } ' +
            baseClass + ':active { transform: translateY(0px); box-shadow: 0 1px 3px rgba(0,0,0,0.12) inset; transition: transform 0.08s ease-out, box-shadow 0.08s ease-out; } ' +
            baseClass + '[data-selected="true"] { box-shadow: 0 3px 8px rgba(0,0,0,0.15), inset 0 1px 0 rgba(255,255,255,0.2); transform: translateY(-1px); font-weight: 700; } ' +
            baseClass + '[data-selected="true"]:hover { box-shadow: 0 4px 10px rgba(0,0,0,0.18), inset 0 1px 0 rgba(255,255,255,0.2); transform: translateY(-2px); } ' +
            baseClass + '[data-selected="true"]:active { transform: translateY(0px); box-shadow: 0 2px 5px rgba(0,0,0,0.15) inset; } ' +
            baseClass + ':focus-visible { outline: 2px solid rgba(0,123,255,0.7); outline-offset: 3px; box-shadow: 0 2px 4px rgba(0,0,0,0.1), 0 0 0 3px rgba(0,123,255,0.2); } ';
        }

        function createSelectedStateStyles(baseClass, options) {
            var css = baseClass + '::before { background-color: ' + (options.defaultBackground || '#ffffff') + '; } ' +
                baseClass + ':hover::before { background-color: ' + (options.hoverBackground || options.defaultBackground || '#f5f5f5') + '; } ' +
                baseClass + '[data-selected="true"]::before { background-color: ' + (options.selectedBackground || 'inherit') + '; } ';

            if (options.selectedHoverBackground) {
                css += baseClass + '[data-selected="true"]:hover::before { background-color: ' + options.selectedHoverBackground + '; } ';
            }

            var selectedDeclarations = [];
            if (options.selectedBorderColor) {
                selectedDeclarations.push('border-color: ' + options.selectedBorderColor);
            }
            if (options.selectedBorderWidth) {
                selectedDeclarations.push('border-width: ' + options.selectedBorderWidth);
            }
            if (options.selectedBoxShadow) {
                selectedDeclarations.push('box-shadow: ' + options.selectedBoxShadow);
            }
            if (selectedDeclarations.length > 0) {
                css += baseClass + '[data-selected="true"] { ' + selectedDeclarations.join('; ') + '; } ';
            }

            if (options.haloColor) {
                css += baseClass + '[data-selected="true"]::after { content: ""; position: absolute; inset: ' + (options.haloInset || '-4px') + '; border-radius: ' + (options.haloRadius || '10px') + '; border: 2px solid ' + options.haloColor + '; pointer-events: none; opacity: ' + (options.haloOpacity || '0.9') + '; } ';
            }

            return css;
        }

        function markCiteText(citetext) {
            var sentiment = citetext.attr('data-sentiment');
            if (!sentiment || !sentimentColors[sentiment]) {
                throw new Error('Invalid sentiment: ' + sentiment);
            }
            citetext.css({
                'text-decoration': 'underline',
                'text-decoration-style': 'double',
                'text-decoration-color': sentimentColors[sentiment]
            });
        }

        function clearCiteText() {
            $(".citetext").css(cssClear);
        }

        function showAllParas() {
            $(".judgments").children().each(function() {
                var child = $(this);
                if (child.hasClass('hidden_text')){
                    return;
                }
                child.show();
            });
        }

        function selectCiteText(parts) {
            var hide = true;
            $(".judgments").children().each(function() {
                var child = $(this);
                var structure = child.attr('data-structure');
                var tagname = child.prop("tagName");
                if (tagname == 'H2'){
                    return;
                }
                if (child.hasClass('hidden_text')){
                    return;
                }
                if (hide == false && structure == null) {
                    hide = false;
                } else {
                    hide = true;
                }
                child.find('.citetext').each(function() {
                    var citetext = $(this);
                    var senti = citetext.attr('data-sentiment');
                    if (senti != null && (parts.length == 0 || parts.includes(senti))) {
                        hide = false;
                        markCiteText(citetext);
                    }
                });
                if (hide) {
                    child.hide();
                } else {
                    child.show();
                }
            });
        }

        function applyStructureFilter(parts) {
            var hide = parts.length === 0 ? false : true;
            var bgcolor = 'white';
            $(".judgments").children().each(function() {
                var child = $(this);
                if (child.prop("tagName") == 'H2') {
                    return;
                }
                if (child.hasClass('hidden_text')) {
                    return;
                }
                var structure = child.attr('data-structure');
                if (structure != null && parts.length > 0) {
                    if (parts.includes(structure)) {
                        bgcolor = palette[structure];
                        hide = false;
                    } else {
                        hide = true;
                    }
                }
                if (hide) {
                    child.hide();
                } else {
                    child.css('background-color', bgcolor);
                    child.show();
                }
            });
        }

        var structdict = {};
        structNames.forEach(function(name) {
            structdict[name] = 0;
        });
        var numstructs = 0;
        var title = null;
        $(".judgments").children().each(function() {
            var child = $(this);
            var structure = child.attr('data-structure');
            if (structure != null) {
                title = titledict[structure];
                structdict[structure] += 1;
                numstructs += 1;
            }
            if (title != null) {
                child.attr('title', title);
            }
        });

        if (numstructs <= 6) {
            return;
        }

        var htmlButtons = [];
        structNames.forEach(function(structure, i) {
            if (structdict[structure] > 0) {
                htmlButtons.push(createButtonHtml('structchk' + i, 'strchk', 'structure', structure, button_names[structure], 'background-color:' + palette[structure]));
            }
        });

        var buttons = createButtonRow(htmlButtons, 2);
        var entiredoc = '<div style="margin-top: 15px; padding-top: 15px; border-top: 1px solid #ddd;">' +
            createToggleSwitch('For entire doc:', 'entireDocSwitch', 'unmarkLabel', 'markLabel', '10px') +
            '</div>';

        var htmlFieldset = createFieldset('Select the following parts of the judgment',
            'https://blog.indiankanoon.org/2024/01/classifying-structure-of-court.html',
            'structblog',
            '<table>' + buttons + '</table>' + entiredoc);
        $("#structuralanal").append(htmlFieldset);

        $('#structural_section').show();
        initBlogButton("#structblog");

        var css = '.slider:before { position: absolute; content: ""; height: 22px; width: 22px; left: 3px; bottom: 3px; background-color: white; transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1); border-radius: 50%; box-shadow: 0 2px 4px rgba(0,0,0,0.2), 0 1px 2px rgba(0,0,0,0.1); } ' +
            'input:checked + .slider { background: linear-gradient(135deg, #4CAF50 0%, #45a049 100%); box-shadow: 0 2px 8px rgba(76,175,80,0.4), inset 0 1px 2px rgba(255,255,255,0.2); } ' +
            'input:checked + .slider:before { transform: translateX(24px); box-shadow: 0 3px 6px rgba(0,0,0,0.25), 0 1px 3px rgba(0,0,0,0.15); } ' +
            '.switch:hover .slider { box-shadow: inset 0 2px 6px rgba(0,0,0,0.15); } ' +
            '.switch:hover input:checked + .slider { box-shadow: 0 3px 10px rgba(76,175,80,0.5), inset 0 1px 2px rgba(255,255,255,0.2); } ' +
            '.toggle-label:hover { transform: scale(1.05); opacity: 0.9; } ' +
            '.strbutton { border: 2px solid rgba(0,0,0,0.15); background-color: inherit; font-size: 1.15rem; line-height: 1.5; padding: 12px 18px; } ' +
            createButtonStyles('.strbutton', 'rgba(255,255,255,0.4)', 'rgba(255,255,255,0.25)') +
            createSelectedStateStyles('.strbutton', {
                defaultBackground: '#ffffff',
                hoverBackground: '#f5f5f5',
                selectedBackground: 'inherit',
                selectedHoverBackground: 'inherit',
                selectedBorderColor: 'rgba(0,0,0,0.35)',
                selectedBorderWidth: '3px',
                selectedBoxShadow: '0 4px 10px rgba(0,0,0,0.2), inset 0 1px 0 rgba(255,255,255,0.25)',
                haloColor: 'rgba(0,0,0,0.08)'
            }) +
            '.citetextbutton { border: 2px solid; background-color: rgba(255,255,255,0.5); transition: transform 0.2s ease-out, box-shadow 0.2s ease-out, border-width 0.2s ease, background-color 0.2s ease; min-height: 58px; display: flex; align-items: center; justify-content: flex-start; box-sizing: border-box; font-size: 1.05rem; line-height: 1.4; padding: 12px 18px; } ' +
            '.citetextbutton:hover { border-width: 2.5px; background-color: rgba(255,255,255,0.7); } ' +
            createButtonStyles('.citetextbutton', 'rgba(0,0,0,0.08)', 'rgba(0,0,0,0.04)') +
            createSelectedStateStyles('.citetextbutton', {
                defaultBackground: '#ffffff',
                hoverBackground: '#f5f5f5',
                selectedBackground: 'inherit',
                selectedHoverBackground: 'inherit',
                selectedBorderColor: 'currentColor',
                selectedBorderWidth: '3px',
                selectedBoxShadow: '0 4px 10px rgba(0,0,0,0.2), inset 0 1px 0 rgba(255,255,255,0.25)',
                haloColor: 'rgba(0,0,0,0.08)'
            }) +
            '#citeselect-button { display: inline-block; margin: 0 auto; min-width: 200px; border-radius: 6px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); transition: all 0.2s ease; } ' +
            '#citeselect-button:hover { box-shadow: 0 4px 8px rgba(0,0,0,0.15); transform: translateY(-1px); } ' +
            '#citeselect-button:active { transform: translateY(0px); box-shadow: 0 2px 4px rgba(0,0,0,0.1); } ' +
            '#citeselect-button .ui-selectmenu-text { font-weight: 500; color: #2196F3; } ';

        $('<style>' + css + '</style>').appendTo('head');

        $(document).on("click", ".strbutton, .citetextbutton", function() {
            var button = $(this);
            toggleButtonSelection(button);
            // Sync the hidden checkbox
            var inputId = button.attr('data-input-id');
            if (inputId) {
                var checkbox = $('#' + inputId);
                if (checkbox.length) {
                    checkbox.prop('checked', button.attr('data-selected') === 'true');
                    checkbox.trigger('change');
                }
            }
        });

        $(document).on("click", ".toggle-label", function() {
            var labelId = $(this).attr('id');
            var switchId = labelId.replace('UnmarkLabel', 'Switch').replace('MarkLabel', 'Switch').replace('unmarkLabel', 'Switch').replace('markLabel', 'Switch');
            var checkbox = $('#' + switchId);
            if (checkbox.length) {
                checkbox.prop('checked', labelId.includes('Mark') || labelId.includes('mark')).trigger('change');
            }
        });

        $("input[name='structure']").on("change", function (e) {
            var parts = [];
            $("input[name='structure']").each(function (i, obj) {
                if (obj.checked) {
                    parts.push(obj.getAttribute('value'));
	        }
            });
            var hide = true;
            if (parts.length == 0){
                hide= false;
            }
            var bgcolor = 'white';
            $(".judgments").children().each (function() {
                var child = $(this);
                if (child.prop("tagName") == 'H2'){
                    return;
                }
                if (child.hasClass('hidden_text')){
                    return;
                }
                var structure = child.attr('data-structure');
                if (structure != null && parts.length > 0) {
                    if ( parts.includes(structure)) {
                        bgcolor = palette[structure];
                        hide = false;
                    } else {
                        hide = true;
                    }
                }
                if (hide) {
                    child.hide();
                } else {
                    child.css('background-color', bgcolor);
                    child.show();
                }
            });
	});

        $("#entireDocSwitch").on("change", function() {
            $("input[name='structure']").each(function (i, obj) {
                obj.checked=false;
            });
            $("button[name='structure_button']").attr('data-selected', 'false');
            updateLabelColors('unmarkLabel', 'markLabel', this.checked);
            if (this.checked) {
                var bgcolor = '';
                $(".judgments").children().each(function() {
                    var child = $(this);
                    if (child.hasClass('hidden_text')) {
                        return;
                    }
                    var structure = child.attr('data-structure');
                    if (structure != null) {
                        bgcolor = palette[structure];
                    }
                    if (bgcolor) {
                        child.css('background-color', bgcolor);
                    }
                    child.show();
                });
            } else {
                $(".judgments").children().each(function() {
                    var child = $(this);
                    if (child.hasClass('hidden_text')) {
                        return;
                    }
                    child.css('background-color', '');
                    child.show();
                });
            }
        });			

        if ($(".citetext").length > 0) {
            var precedentSwitch = createToggleSwitch('View precedents:', 'precedentSwitch', 'precedentUnmarkLabel', 'precedentMarkLabel');
            var citetextOnly = createToggleSwitch('View only precedents:', 'onlycitetext', 'onlyPrecedentUnmarkLabel', 'onlyPrecedentMarkLabel');
            var citeSelect = '<div style="margin: 12px 0; text-align: center;"><select name="cites" id="citeselect" style="min-width: 200px; padding: 8px 12px; border-radius: 6px; border: 1px solid #e0e0e0; font-size: 0.9em; cursor: pointer; background-color: white; transition: all 0.2s ease;"><option value="" selected>Select precedent ...</option></select></div>';
            var htmlFieldset = createFieldset('View how precedents are cited in this document',
                'https://blog.indiankanoon.org/2024/01/cite-text-extraction-and-reliability-of.html',
                'citeblog',
                precedentSwitch + citetextOnly + citeSelect);

            var citeButtons = [];
            var existingSentiments = new Set();
            $('.citetext').each(function() {
                var sentiment = $(this).attr('data-sentiment');
                if (sentiment) {
                    existingSentiments.add(sentiment);
                }
            });
            sentimentNames.forEach(function(name, i) {
                if (existingSentiments.has(name)) {
                    citeButtons.push(createButtonHtml('citetxtchk' + i, 'citetextchk', 'citetext', name, sentimentLabels[name], 'border-color:' + sentimentColors[name]));
                }
            });
            var rows = createButtonRow(citeButtons, 2);
            var sentimentFieldset = '<fieldset><legend>Filter precedents by opinion of the court</legend><table>\n' + rows + '</table></fieldset>';

            $('#citetextdash').append(htmlFieldset);
            $('#citetextdash').append(sentimentFieldset);

            $('#citetext_section').show();
            initBlogButton("#citeblog");

            var ctids = new Set();
            $('.citetext').each(function() {
                var docid = $(this).attr('data-docid');
                if (docid) {
                    ctids.add(docid);
                }
            });

            var docids = new Set();
            var citeselect = $('#citeselect');
            $('a').each(function() {
                var href = $(this).attr('href');
                if (!href) {
                    return;
                }
                var words = href.split('/');
                if (words.length >= 3 && words[1] === 'doc') {
                    var docid = words[2];
                    if (ctids.has(docid) && !docids.has(docid)) {
                        docids.add(docid);
                        citeselect.append('<option value="' + docid + '">' + $(this).text() + '</option>');
                    }
                }
            });

            $("input[name='citetext']").on("change", function (e) {
                var parts = [];
                $("input[name='citetext']").each(function (i, obj) {
                    if (obj.checked) {
                        parts.push(obj.getAttribute('value'));
                    }
                });
                if (parts.length > 0) {
                    selectCiteText(parts);
                } else {
                    clearCiteText();
                    showAllParas();
                }
            });

            $('#citeselect').selectmenu();
            $('#citeselect-button').parent().css({'text-align': 'center', 'display': 'flex', 'justify-content': 'center'});
            $('#citeselect').on('selectmenuselect', function() {
                var docid = this.value;
                clearCiteText();
                if (docid) {
                    var hide = true;
                    clearCiteText();
                    $(".judgments").children().each(function() {
                        var child = $(this);
                        if (child.hasClass('hidden_text')){
                            return;
                        }
                        var structure = child.attr('data-structure');
                        var tagname = child.prop("tagName");
                        if (tagname == 'H2'){
                            return;
                        }
                        var citenodes = []
                        if (hide == false && structure == null) {
                            hide = false;
                        } else {
                            hide = true;
                            child.find('.citetext').each(function() {
                                var citetext = $(this);
                                if (citetext.attr('data-docid') == docid) {
                                    hide = false;
                                    citenodes.push(citetext);
                                }
                            });
                        }
                        if (hide) {
                            child.hide();
                        } else {
                            child.show();
                            for (var i = 0; i < citenodes.length; i++) {
                                markCiteText(citenodes[i]);
                            }
                        }
                    });
                    $('#citeselect option:first').text('Deselect precedent');
                } else {
                    showAllParas();
                    $('#citeselect option:first').text('Select precedent ...');
                    $('#citeselect').val('');
                }
                $('#citeselect').selectmenu('refresh');
            });

            $('#onlycitetext').on("change", function() {
                updateLabelColors('onlyPrecedentUnmarkLabel', 'onlyPrecedentMarkLabel', this.checked);
                clearCiteText();
                if (this.checked) {
                    selectCiteText([]);
                } else {
                    showAllParas();
                }
            });

            $('#precedentSwitch').on("change", function() {
                updateLabelColors('precedentUnmarkLabel', 'precedentMarkLabel', this.checked);
                if (this.checked) {
                    $(".judgments").children().each(function() {
                        var child = $(this);
                        if (child.hasClass('hidden_text')){
                            return;
                        }
                        child.show();
                    });
                    $(".citetext").each(function() {
                        markCiteText($(this));
                    });
                } else {
                    clearCiteText();
                    showAllParas();
                }
            });
        }

});    
