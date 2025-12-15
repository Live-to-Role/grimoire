"""Import DTRPG library directly using sqlite3."""
import json
import re
import sqlite3
from pathlib import Path


def normalize(fn):
    name = Path(fn).stem.lower()
    name = re.sub(r'[-_.]', ' ', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def main():
    # Load DTRPG data
    with open('/tmp/my_drivethrurpg.json', 'r') as f:
        data = json.load(f)

    # Build filename index
    index = {}
    for item in data.get('data', []):
        product = item.get('product', {})
        publisher = item.get('publisher', {})
        title = product.get('title', '').strip()
        pub_name = publisher.get('title', '').strip()
        for f in product.get('files', []):
            fn = f.get('title', '')
            if fn:
                norm = normalize(fn)
                if norm:
                    index[norm] = {'title': title, 'publisher': pub_name}

    print(f'Built index with {len(index)} filenames from DTRPG')

    # Connect to DB and update
    conn = sqlite3.connect('/app/data/grimoire.db')
    cursor = conn.cursor()

    # Get products
    cursor.execute(
        'SELECT id, file_name, title, publisher FROM products '
        'WHERE is_duplicate = 0 AND is_missing = 0'
    )
    rows = cursor.fetchall()
    print(f'Found {len(rows)} local products')

    matched = 0
    updated = 0
    for row in rows:
        pid, fname, title, publisher = row
        norm = normalize(fname)
        if norm in index:
            matched += 1
            dtrpg = index[norm]
            updates = []
            params = []
            if not publisher and dtrpg['publisher']:
                updates.append('publisher = ?')
                params.append(dtrpg['publisher'])
            if title == Path(fname).stem and dtrpg['title']:
                updates.append('title = ?')
                params.append(dtrpg['title'])
            if updates:
                params.append(pid)
                sql = f"UPDATE products SET {', '.join(updates)} WHERE id = ?"
                cursor.execute(sql, params)
                updated += 1

    conn.commit()
    conn.close()
    print(f'Matched: {matched}, Updated: {updated}')


if __name__ == '__main__':
    main()
