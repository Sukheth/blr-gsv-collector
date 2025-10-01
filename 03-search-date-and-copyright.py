import os
import time
import sqlite3
import streetview
import concurrent.futures
import json
import csv
from tqdm import tqdm
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

DB_PATH = "gsv.db"
PROGRESS_CSV = "progress/03-search-date-and-copyright-progress.csv"
PROGRESS_JSON = "progress/03-search-date-and-copyright-progress.json"

# Create progress directory if it doesn't exist
os.makedirs("progress", exist_ok=True)

GOOGLE_MAP_API_KEY = os.getenv("GOOGLE_MAP_API_KEY")

if GOOGLE_MAP_API_KEY is None:
    raise ValueError("GOOGLE_MAP_API_KEY is not set")

SEARCH_BATCH_SIZE = 100000


########################################
# MARK: Database setup
########################################


def setup_database():
    print("Setting up database")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute(
        """CREATE TABLE IF NOT EXISTS sample_coords
            (id INTEGER PRIMARY KEY AUTOINCREMENT, lat real, lon real, label text, searched boolean default False)
            """
    )
    cursor.execute(
        """
    CREATE TABLE IF NOT EXISTS search_panoramas (
        pano_id TEXT PRIMARY KEY,
        lat REAL,
        lon REAL,
        date TEXT,
        copyright TEXT,
        heading REAL,
        pitch REAL,
        roll REAL
    )
    """
    )

    conn.commit()
    conn.close()


########################################
# MARK: Get panoramas without date and copyright
########################################


def get_panoramas_without_date_and_copyright(batch_size: int) -> list[str]:
    conn = sqlite3.connect(DB_PATH)
    panoramas = []

    cursor = conn.execute(
        "SELECT * FROM search_panoramas WHERE date IS NULL OR date = '' OR copyright IS NULL OR copyright = '' ORDER BY RANDOM() LIMIT ?",
        [batch_size],
    )

    rows = cursor.fetchall()

    print(f"Found {len(rows)} panoramas without date and copyright")

    for row in rows:
        (pano_id, lat, lon, date, copyright, heading, pitch, roll) = row
        panoramas.append(pano_id)

    conn.close()

    return panoramas


########################################
# MARK: Search and update metadata
########################################


def log_progress(pano_id, status, date=None, copyright=None, error=None):
    """Log progress to CSV and JSON files"""
    progress_entry = {
        "timestamp": datetime.now().isoformat(),
        "pano_id": pano_id,
        "status": status,  # 'success', 'no_metadata', 'error'
        "date": date,
        "copyright": copyright,
        "error": error
    }

    # Update CSV
    write_header = not os.path.exists(PROGRESS_CSV) or os.path.getsize(PROGRESS_CSV) == 0
    with open(PROGRESS_CSV, 'a', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=progress_entry.keys())
        if write_header:
            writer.writeheader()
        writer.writerow(progress_entry)

    # Update JSON
    if os.path.exists(PROGRESS_JSON):
        with open(PROGRESS_JSON, 'r') as f:
            all_data = json.load(f)
    else:
        all_data = []
    all_data.append(progress_entry)
    with open(PROGRESS_JSON, 'w') as f:
        json.dump(all_data, f, indent=2)


def search_and_update(pano_id):
    try:
        metadata = streetview.get_panorama_meta(pano_id, GOOGLE_MAP_API_KEY)

        if metadata is None or (metadata.date is None and metadata.copyright is None):
            log_progress(pano_id, 'no_metadata')
            return

        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "UPDATE search_panoramas SET date = ?, copyright = ? WHERE pano_id = ?",
            [metadata.date, metadata.copyright, pano_id],
        )
        conn.commit()
        conn.close()

        log_progress(pano_id, 'success', date=metadata.date, copyright=metadata.copyright)
    except Exception as e:
        log_progress(pano_id, 'error', error=str(e))


def run_batch_in_parallel():
    panoramas = get_panoramas_without_date_and_copyright(SEARCH_BATCH_SIZE)

    if len(panoramas) == 0:
        print("No panoramas without date and copyright found, exiting")
        exit(0)

    panorama_count = len(panoramas)
    begin_time = time.time()

    with concurrent.futures.ThreadPoolExecutor(max_workers=72) as executor:
        futures = {
            executor.submit(search_and_update, pano_id): pano_id
            for pano_id in panoramas
        }

        with tqdm(total=panorama_count, desc="Fetching metadata", unit="panos") as pbar:
            for future in concurrent.futures.as_completed(futures):
                pano_id = futures[future]
                try:
                    future.result()
                except Exception as e:
                    print(f"Error searching for panorama {pano_id}: {e}")

                pbar.update(1)
                total_duration = time.time() - begin_time
                total_speed = pbar.n / total_duration if total_duration > 0 else 0
                pbar.set_postfix({"speed": f"{total_speed:.2f} panos/sec"})


if __name__ == "__main__":
    setup_database()

    while True:
        run_batch_in_parallel()
