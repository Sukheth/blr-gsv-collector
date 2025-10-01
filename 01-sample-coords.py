import geopandas as gpd
import numpy as np
from shapely.geometry import Point
from shapely.prepared import prep
import os
import time
import sqlite3
import json
import csv
from tqdm import tqdm
from datetime import datetime

# allegedly the Google Street View API will return the nearest panorama within 50 meters radius
# but I'm sampling every 5 meters, because I've seen missing panoramas in the past
# Increased to 25 meters for faster processing
SAMPLE_INTERVAL_METER = 25
# 1 degree is approximately 111000 meters
SAMPLE_INTERVAL_DEGREE = SAMPLE_INTERVAL_METER / 111000

PRINT_INTERVAL = 1000  # print every 1000 points
DB_PATH = "gsv.db"
PROGRESS_CSV = "progress/01-sample-coords-progress.csv"
PROGRESS_JSON = "progress/01-sample-coords-progress.json"

# Create progress directory if it doesn't exist
os.makedirs("progress", exist_ok=True)

geojson_path = "geojson/BBMP_Zones.geojson"

gdf = gpd.read_file(geojson_path)
print(gdf.head())

feature_dict = {}
for i, feature in gdf.iterrows():
    # make feature a new gdf
    feature_gdf = gpd.GeoDataFrame([feature])
    feature_dict[feature["namecol"]] = feature_gdf

print("Feature dict: ", feature_dict.keys())


def create_point_grid(bounds, interval):
    x = np.arange(bounds[0], bounds[2], interval)
    y = np.arange(bounds[1], bounds[3], interval)
    xx, yy = np.meshgrid(x, y)
    points = [Point(x, y) for x, y in zip(xx.ravel(), yy.ravel())]
    return points


def get_points_in_polygon(points, polygon, label, zone_name):
    points_in_polygon = []
    progress_data = []

    with tqdm(total=len(points), desc=f"Checking {label}", unit="pts") as pbar:
        for i, point in enumerate(points):
            in_polygon = polygon.contains(point)
            if in_polygon:
                points_in_polygon.append(point)

            # Record progress every 100 points
            if i % 100 == 0 or i == len(points) - 1:
                progress_entry = {
                    "timestamp": datetime.now().isoformat(),
                    "zone": zone_name,
                    "label": label,
                    "checked_points": i + 1,
                    "total_points": len(points),
                    "found_points": len(points_in_polygon),
                    "progress_pct": round((i + 1) / len(points) * 100, 2)
                }
                progress_data.append(progress_entry)

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

            pbar.update(1)

    return points_in_polygon


def save_points_to_db(points, label):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Create table if not exists
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS sample_coords
                (id INTEGER PRIMARY KEY AUTOINCREMENT, lat real, lon real, label text, searched boolean default False)"""
    )
    conn.commit()

    # Insert a row of data
    for point in points:
        cursor.execute(
            "INSERT INTO sample_coords VALUES (NULL, ?, ?, ?, ?)",
            (point.y, point.x, label, False),
        )
    conn.commit()
    conn.close()


for zone in feature_dict.keys():
    print("Processing zone: ", zone)
    gdf = feature_dict[zone]

    # each zone is a multi-polygon, so we need to explode it into individual polygons
    gdf = gdf.explode(index_parts=True)
    print("Exploded gdf: ", gdf.head())

    points_in_zone = []

    # make each individual polygon a new gdf
    for polygon_idx, polygon in enumerate(gdf["geometry"]):
        process_label = f"{zone} - polygon {polygon_idx}"
        print("Processing %s" % process_label)

        polygon_gdf = gpd.GeoDataFrame([polygon], columns=["geometry"])
        bb = polygon_gdf.total_bounds
        polygon_prepared = prep(polygon)

        # sample points in the bounding box based on INTERVAL
        points_in_bbox = create_point_grid(bb, SAMPLE_INTERVAL_DEGREE)

        print(f"Total points in bounding box: {len(points_in_bbox)}")

        points_in_polygon = get_points_in_polygon(
            points_in_bbox, polygon_prepared, process_label, zone
        )
        print(f"Total points in {process_label}: {len(points_in_polygon)}")
        points_in_zone.extend(points_in_polygon)

    print(f"Total points in {zone}: {len(points_in_zone)}")
    print("Saving points to db")
    save_points_to_db(points_in_zone, zone)
