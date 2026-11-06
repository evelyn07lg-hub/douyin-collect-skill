"""Read-only DOCX verification for append operations; never edits a package."""
import copy
import difflib
import hashlib
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

NS={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
W='{'+NS['w']+'}'



def merge_identical_text_runs(paragraph):
    """Ignore editor-only run splitting; preserve exact text and character properties."""
    previous = None
    previous_key = None
    for child in list(paragraph):
        parts = list(child)
        tags = [part.tag for part in parts]
        if child.tag != W+'r' or tags not in ([W+'t'], [W+'rPr', W+'t']):
            previous = previous_key = None
            continue
        text = parts[-1]
        properties = ET.tostring(parts[0]) if len(parts) == 2 else None
        key = (tuple(sorted(child.attrib.items())), properties,
               tuple(sorted(text.attrib.items())), child.text, child.tail, text.tail)
        if previous is not None and key == previous_key:
            previous[-1].text = (previous[-1].text or '') + (text.text or '')
            paragraph.remove(child)
        else:
            previous, previous_key = child, key


def snapshot(path):
    path=Path(path)
    with zipfile.ZipFile(path) as package:
        if package.testzip() is not None:
            raise ValueError('invalid DOCX backup')
        doc=ET.fromstring(package.read('word/document.xml'))
        paragraphs=doc.findall('w:body/w:p',NS)
        # _GoBack is the editor's last-caret marker, not user content/formatting.
        ignored={e.get(W+'id') for e in doc.iter(W+'bookmarkStart') if e.get(W+'name')=='_GoBack'}
        canonical=[]
        for paragraph in paragraphs:
            node=copy.deepcopy(paragraph)
            for parent in node.iter():
                for child in list(parent):
                    if child.tag in (W+'bookmarkStart',W+'bookmarkEnd') and child.get(W+'id') in ignored:
                        parent.remove(child)
            # WPS clears the Chinese input locale on the paragraph-end mark when
            # Enter creates a following paragraph. It is not a property of text runs.
            # Retain all fonts/sizes and all actual text-run language properties.
            mark = node.find('w:pPr/w:rPr', NS)
            if mark is not None:
                for language in list(mark):
                    if language.tag == W+'lang' and language.attrib == {W+'eastAsia':'zh'}:
                        mark.remove(language)
                if not len(mark) and not mark.attrib and not (mark.text or '').strip():
                    node.find('w:pPr', NS).remove(mark)
            merge_identical_text_runs(node)
            canonical.append(ET.tostring(node))
        protected={name:package.read(name) for name in package.namelist() if name in ('word/styles.xml','word/numbering.xml')
            or name.startswith(('word/theme/','word/media/','word/header','word/footer'))}
        fonts={}
        if 'word/fontTable.xml' in package.namelist():
            fonts={node.get(W+'name'):ET.tostring(node) for node in ET.fromstring(package.read('word/fontTable.xml'))}
        body=doc.find('w:body',NS)
        layout=ET.tostring(body.find('w:sectPr',NS)) if body.find('w:sectPr',NS) is not None else None
        return {'page_break_before':[node.find('w:pPr/w:pageBreakBefore',NS) is not None and node.find('w:pPr/w:pageBreakBefore',NS).get(W+'val','1') not in ('0','false','off') for node in paragraphs],
            'paragraphs':[''.join(e.text or '' for e in node.iter(W+'t')) for node in paragraphs],
            'canonical':canonical,'protected':protected,'fonts':fonts,'section_layout':layout,
            'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}


def sections(data, account_names):
    paragraphs=data['paragraphs'];anchors=[]
    for name in account_names:
        locations=[i for i,text in enumerate(paragraphs) if ''.join(text.split())==''.join(name.split())]
        if len(locations)!=1:
            raise ValueError('account heading missing or duplicated: '+name)
        anchors.append((locations[0],name))
    anchors.sort()
    return {name:{'start':index,'end':anchors[i+1][0] if i+1<len(anchors) else len(paragraphs)}
            for i,(index,name) in enumerate(anchors)}


def verify_section_append(before, after, expected_lines, account, account_names):
    boundary=sections(before,account_names)[account]['end']
    changes=[(op,i,j,k,l) for op,i,j,k,l in difflib.SequenceMatcher(a=before['canonical'],b=after['canonical'],autojunk=False).get_opcodes() if op!='equal']
    if not changes or any(op!='insert' or i!=boundary or i!=j for op,i,j,k,l in changes):
        raise ValueError('append changed old content/format or inserted outside account boundary')
    actual=[text for op,i,j,k,l in changes for text in after['paragraphs'][k:l]]
    compact=lambda values:''.join(''.join(values).split())
    if compact(actual)!=compact(expected_lines):
        raise ValueError('inserted text incomplete or altered')
    if before['protected']!=after['protected'] or before['section_layout']!=after['section_layout']:
        raise ValueError('existing styles, media, headers or page layout changed')
    if any(after['fonts'].get(name)!=value for name,value in before['fonts'].items()):
        raise ValueError('existing font definitions changed')
    return {'account_section_verified':True,'existing_content_preserved':True,'existing_format_preserved':True,
            'new_text_complete':True,'inserted_paragraphs':len(actual),'before_sha256':before['sha256'],'after_sha256':after['sha256']}

def verify_account_page_breaks(data, account_names):
    bounds = sections(data, account_names)
    for name, value in bounds.items():
        if not data.get('page_break_before', [])[value['start']]:
            raise ValueError('account heading requires explicit page-break-before: ' + name)
    return {'all_account_headings_start_new_page': True}
