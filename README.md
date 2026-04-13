# ECPC Analytics

ECPC Analytics is a web-based platform for analyzing competitive programming contests across multiple years.  
It provides structured insights into problem difficulty, topic distribution, and contest composition.

## Overview

The system aggregates contest data and transforms it into meaningful analytics that help understand:

- how problem difficulty is distributed across contests  
- which topics appear most frequently  
- differences between qualification rounds and finals  
- detailed breakdown of problems within each contest  

## Screenshots

### Dashboard

![Dashboard](./screenshots/dashboard.png)

The dashboard provides a high-level overview of all contests, including total problems, average solve rate, difficulty distribution, and topic frequency.

### Problems Explorer

![Problems Explorer](./screenshots/problems.png)

The problems explorer allows searching and filtering problems by difficulty, topic, and contest.  
It is designed to quickly navigate large datasets and extract specific insights.

### Contest Analysis

![Contest Analysis](./screenshots/contest.png)

Each contest page presents a detailed breakdown including difficulty distribution, top topics, per-day structure, and hardest and easiest problems.

## Features

- Difficulty distribution analysis  
- Topic frequency analysis  
- Advanced problem search and filtering  
- Qualification and finals comparison  
- Per-contest and per-day analytics  
- Clean and responsive interface  

## Architecture

The project follows a simple and effective structure:

- Flask backend for data processing and API endpoints  
- JSON-based dataset for contest problems  
- Server-rendered templates for UI  
- JavaScript for dynamic rendering and interaction  

## Tech Stack

- Python (Flask)  
- JavaScript  
- Tailwind CSS  
- Chart.js  

## Run Locally

Install dependencies:

pip install -r requirements.txt

Run the application:

python app/app.py

Open in browser:

http://localhost:5000

## Access to Problems

To open the problems directly on Codeforces, you need to join the ACPC Scientific Committee Archive.

You can join from here:
https://codeforces.com/group/Rilx5irOux/blog

This archive is one of the main and most reliable sources for Egyptian contests, and access is required to view the problems.


## Project Structure

app/  
 app.py  
 templates/  
 static/  
 ICPCRoad/  

screenshots/  
README.md  
LICENSE  
requirements.txt  

## Author

Adham Ahmed

## License

All rights reserved © 2026 Adham Ahmed
