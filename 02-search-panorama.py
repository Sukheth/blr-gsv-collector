import os
import time
import sqlite3
import streetview
import concurrent.futures
import json
import csv
from tqdm import tqdm
from datetime import datetime

DB_PATH = "gsv.db"
PROGRESS_CSV = "progress/02-search-panorama-progress.csv"
PROGRESS_JSON = "progress/02-search-panorama-progress.json"

# Create progress directory if it doesn't exist
os.makedirs("progress", exist_ok=True)

SEARCH_BATCH_SIZE = 100000

# if you are skeptical about the API results affected by the network, you can set this to False
# and the coords that have no panorama found will not be marked as searched, and will be searched again in the future
COUNT_NONE_FOUND_AS_SEARCHED = True

WORKERS = 72


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
# MARK: Get unsearched coords
########################################


def get_unsearched_coords(batch_size: int) -> dict[int, tuple[float, float]]:
    conn = sqlite3.connect(DB_PATH)
    coords: dict[int, tuple[float, float]] = {}

    cursor = conn.execute(
        "SELECT id, lat, lon, label, searched FROM sample_coords WHERE searched = 0 ORDER BY RANDOM() LIMIT ?",
        [batch_size],
    )

    rows = cursor.fetchall()

    print(f"Found {len(rows)} unsearched coords")

    for row in rows:
        (id, lat, lon, label, searched) = row
        coords[id] = (lat, lon)

    conn.close()

    return coords


########################################
# MARK: Search panorama
########################################


def log_progress(coord_id, lat, lon, status, panoramas_found=0, error=None):
    """Log progress to CSV and JSON files"""
    progress_entry = {
        "timestamp": datetime.now().isoformat(),
        "coord_id": coord_id,
        "lat": round(lat, 6),
        "lon": round(lon, 6),
        "status": status,  # 'success', 'no_panorama', 'error'
        "panoramas_found": panoramas_found,
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


def search_and_insert(coord_id, lat, lon):
    try:
        panorama_results = streetview.search_panoramas(lat, lon)

        # if result is not a list or is an empty list
        if not isinstance(panorama_results, list):
            log_progress(coord_id, lat, lon, 'error', error='Invalid result type')
            return

        if len(panorama_results) == 0:
            log_progress(coord_id, lat, lon, 'no_panorama')
            if not COUNT_NONE_FOUND_AS_SEARCHED:
                return

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        for result in panorama_results:
            cursor.execute(
                "INSERT OR IGNORE INTO search_panoramas VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    result.pano_id,
                    result.lat,
                    result.lon,
                    result.date,
                    None,
                    result.heading,
                    result.pitch,
                    result.roll,
                ],
            )
        cursor.execute("UPDATE sample_coords SET searched = 1 WHERE id = ?", [coord_id])
        conn.commit()
        conn.close()

        log_progress(coord_id, lat, lon, 'success', panoramas_found=len(panorama_results))
    except Exception as e:
        log_progress(coord_id, lat, lon, 'error', error=str(e))


def run_batch_in_parallel():
    coords = get_unsearched_coords(SEARCH_BATCH_SIZE)

    if len(coords) == 0:
        print("No unsearched coords found, exiting")
        exit(0)

    coords_count = len(coords)
    begin_time = time.time()

    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = {
            executor.submit(search_and_insert, coord_id, lat, lon): coord_id
            for coord_id, (lat, lon) in coords.items()
        }

        with tqdm(total=coords_count, desc="Searching panoramas", unit="coords") as pbar:
            for future in concurrent.futures.as_completed(futures):
                coord_id = futures[future]
                try:
                    future.result()
                except Exception as e:
                    print(f"Error searching for coord {coord_id}: {e}")

                pbar.update(1)
                total_duration = time.time() - begin_time
                total_speed = pbar.n / total_duration if total_duration > 0 else 0
                pbar.set_postfix({"speed": f"{total_speed:.2f} coords/sec"})


if __name__ == "__main__":
    setup_database()

    while True:
        run_batch_in_parallel()
