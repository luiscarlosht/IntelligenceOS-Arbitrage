"""Literal restriction instructions and independently clickable validated links."""
from urllib.parse import urlsplit


def safe_approval_url(value):
    if not isinstance(value, str) or any(ord(c) <= 32 or ord(c) == 127 for c in value) or '\\' in value:
        return False
    try:
        url = urlsplit(value)
        return url.scheme in ('https', 'http') and bool(url.hostname) and not url.username and not url.password
    except ValueError:
        return False


def write_approval_links(workbook, comparisons):
    sheet = workbook.create_sheet('Amazon approval instructions')
    sheet.append(['ASIN', 'Reason code', 'Instructions / message', 'Link title', 'Link / unknown', 'HTTP method'])
    for row in comparisons:
        links = row.get('approval_links') or []
        for link in links or [{}]:
            sheet.append([row.get('candidate_asin'), link.get('reason_code'), row.get('approval_messages') or 'UNKNOWN',
                          link.get('title'), link.get('resource') or 'UNKNOWN', link.get('verb')])
            cell = sheet.cell(sheet.max_row, 5)
            if safe_approval_url(link.get('resource')) and link.get('verb', 'GET') == 'GET':
                cell.hyperlink = link['resource']
    for row in sheet:
        for cell in row:
            if isinstance(cell.value, str):
                cell.data_type = 's'
    for col, width in zip('ABCDEF', (20, 26, 80, 40, 85, 18)):
        sheet.column_dimensions[col].width = width
