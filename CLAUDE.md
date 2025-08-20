# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Python-based Google Street View data collection tool designed for gathering panorama metadata across Bangalore's 8 BBMP zones. The system uses a multi-threaded approach to efficiently sample coordinates and collect Street View panorama data throughout the city.

## Core Architecture

The project follows a sequential pipeline architecture with four main stages:

1. **Coordinate Sampling** (`01-sample-coords.py`): Generates a grid of coordinates within Bangalore BBMP zone boundaries and stores them in SQLite
2. **Panorama Search** (`02-search-panorama.py`): Searches for Street View panoramas near sampled coordinates using multi-threading
3. **Metadata Collection** (`03-search-date-and-copyright.py`): Enriches panorama data with date and copyright information using Google Maps API
4. **Progress Monitoring** (`04-check-progress.py`): Provides real-time statistics on collection progress

## Database Schema

All data is stored in a single SQLite database (`gsv.db`) with two main tables:

- `sample_coords`: Stores coordinate grid points with search status tracking
- `search_panoramas`: Stores panorama metadata including ID, location, date, copyright, and camera orientation

## Key Configuration

- **Sampling interval**: 5 meters (configurable via `SAMPLE_INTERVAL_METER`)
- **Threading**: 72 workers for parallel processing (configurable in scripts 2 & 3)
- **Batch processing**: 100,000 records per batch
- **Geographic data**: Uses BBMP zones GeoJSON file (`geojson/BBMP_Zones.geojson`)

## Development Commands

### Setup
```bash
pip install -r requirement.txt
```

### Environment Setup
Create a `.env` file with:
```
GOOGLE_MAP_API_KEY=your_api_key_here
```

### Run Pipeline
```bash
# Step 1: Generate coordinate grid
python 01-sample-coords.py

# Step 2: Search for panoramas (runs continuously)
python 02-search-panorama.py

# Step 3: Collect metadata (runs continuously) 
python 03-search-date-and-copyright.py

# Monitor progress (run anytime)
python 04-check-progress.py
```

## Important Notes

- Scripts 2 and 3 run continuously in loops and can be interrupted/resumed
- The SQLite database maintains state between runs
- Multi-threading is heavily used - be mindful of API rate limits
- Bangalore BBMP zone boundaries are defined in `geojson/BBMP_Zones.geojson`
- The system is designed to handle network failures gracefully with retry logic