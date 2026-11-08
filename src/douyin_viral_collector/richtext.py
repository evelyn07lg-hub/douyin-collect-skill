"""Explicit archive formatting, independent of editor selection inheritance."""
import html
import re
import zipfile
import xml.etree.ElementTree as ET
from .wps_integrity import NS, W


def archive_html(lines, headings=(), formatting=None):
    from .document_settings import formatting as resolve_format
    fmt=resolve_format({"document_format":formatting or {}})
    headings = set(headings)
    paragraphs = []
    for text in lines:
        if not text.strip():
            continue
        heading = text in headings
        size = format(fmt['heading_size'] if heading else fmt['body_size'],'g')
        entry = bool(re.match(r'^(?:20\d\d年)?\d{1,2}月\d{1,2}日', text.strip()))
        gap = str(fmt['article_gap'])+'pt' if entry else '0'
        style = (f'font-family:{html.escape(fmt["font"],quote=True)};font-size:{size}pt;margin:0;margin-top:{gap};line-height:{fmt["line_spacing"]*100}%;'
                 f'text-align:{"center" if heading else "left"};'
                 + ('page-break-before:always;' if heading and fmt['account_page_break'] else 'page-break-before:auto;'))
        paragraphs.append(f'<p style="{style}"><span style="font-family:{html.escape(fmt["font"],quote=True)};font-size:{size}pt">{html.escape(text)}</span></p>')
    return '<html><body>'+''.join(paragraphs)+'</body></html>'


def paste_archive(page, lines, headings=(), trim_terminal=True, formatting=None):
    payload={'html':archive_html(lines, headings, formatting),'text':'\n'.join(lines)}
    handled=page.evaluate("""({html,text})=>{
        const data=new DataTransfer();data.setData('text/html',html);data.setData('text/plain',text);
        return !document.activeElement.dispatchEvent(new ClipboardEvent('paste',{
            clipboardData:data,bubbles:true,cancelable:true}));
    }""",payload)
    if not handled:
        raise RuntimeError('Editor did not accept the standard paste event')
    page.wait_for_timeout(3000)
    if trim_terminal:
        page.keyboard.press('Backspace');page.wait_for_timeout(1000)


def verify_archive_format(path, headings, paragraph_indices=None, formatting=None):
    from .document_settings import formatting as resolve_format
    fmt=resolve_format({"document_format":formatting or {}})
    with zipfile.ZipFile(path) as z:
        doc = ET.fromstring(z.read('word/document.xml'))
    paragraphs = doc.findall('w:body/w:p', NS)
    indices = range(len(paragraphs)) if paragraph_indices is None else paragraph_indices
    for index in indices:
        p = paragraphs[index]
        text = ''.join(e.text or '' for e in p.iter(W+'t'))
        if not text.strip():
            # A single terminal document paragraph is allowed; no interior spacers.
            if index != len(paragraphs)-1:
                raise ValueError('Unexpected blank paragraph in archive')
            continue
        heading = text in headings
        size = str(round(2*(fmt['heading_size'] if heading else fmt['body_size'])))  # OOXML half-points: 四号14pt, 五号10.5pt
        page_break = p.find('w:pPr/w:pageBreakBefore',NS)
        if (page_break is not None and page_break.get(W+'val','1') not in ('0','false','off')) != bool(heading and fmt['account_page_break']):
            raise ValueError('Only account headings may force a new page')
        spacing = p.find('w:pPr/w:spacing',NS)
        entry = bool(re.match(r'^(?:20\d\d年)?\d{1,2}月\d{1,2}日', text.strip()))
        before = str(round(fmt['article_gap']*20)) if entry else '0'  # one 10.5pt body line between articles
        if spacing is None or spacing.get(W+'before','0') != before or spacing.get(W+'after','0') != '0':
            raise ValueError('Unexpected paragraph spacing')
        if spacing.get(W+'line') != str(round(fmt['line_spacing']*240)) or spacing.get(W+'lineRule','auto') != 'auto':
            raise ValueError('Expected single line spacing')
        if any(e.get(W+'type')=='page' for e in p.iter(W+'br')):
            raise ValueError('Unexpected manual page break')
        for run in p.findall('w:r',NS):
            if not ''.join(e.text or '' for e in run.iter(W+'t')):
                continue
            fonts=run.find('w:rPr/w:rFonts',NS);sz=run.find('w:rPr/w:sz',NS)
            if fonts is None or fonts.get(W+'eastAsia')!=fmt['font'] or sz is None or sz.get(W+'val')!=size:
                raise ValueError('Archive font or size mismatch')
    return {'configured_archive_format':True} if formatting else {'songti_14pt_headings_10_5pt_body':True,'one_body_line_between_articles':True}
