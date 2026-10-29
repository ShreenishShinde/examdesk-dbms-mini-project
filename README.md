# ExamDesk

**Examination Management Portal — MAD 1 project**

ExamDesk is a small, role-based web application for coordinating examinations, examiner slots, student bookings, and rubric-based results. It uses Flask, Jinja2, HTML/CSS, Bootstrap, and SQLite. The database is created automatically by the application; no manual database setup is needed.

## Run locally

1. Install Python 3.10 or later.
2. Create and activate a virtual environment (recommended).
3. Install dependencies with `pip install -r requirements.txt`.
4. Start the application with `python app.py`.
5. Open `http://127.0.0.1:5000`.

The database file `emp.sqlite3` is created in this folder on first run and is seeded with a sample course, examination, rubric, and administrator account.

### Demo administrator

- Email: `admin@example.com`
- Password: `admin1234`

Change the demo password and set `EMP_SECRET_KEY` before using the application beyond a local demonstration. To start again with a clean sample database, stop the app and delete `emp.sqlite3`; it will be recreated at startup.

## Demo sequence

1. Sign in as the administrator. Approve a registered examiner, create an examination, add rubric criteria, and assign an approved examiner.
2. Sign out. Register as an examiner, then sign in after administrator approval and create a slot within the examination's slot-creation dates.
3. Register as a student, browse slots, and book one during the booking period. A student can have one active booking per examination.
4. Sign in as the examiner to score the student against each rubric criterion and add feedback.
5. Sign in as the administrator and publish results. The student can then view the published score and feedback.

Seeded example data is for demonstration. The sample examination windows are set to October–December 2026 and can be adjusted when creating other examinations.

## Main routes

| Route | Purpose |
| --- | --- |
| `/` | Public examination landing page |
| `/register`, `/login`, `/logout` | Account and session flows |
| `/dashboard` | Role-based dashboard |
| `/exam/<id>/slots` | Student slot selection |
| `/examiner/evaluations` | Examiner evaluation queue |
| `/results` | Student's published rubric scores |
| `/admin/bookings` | Administrator booking history |

## Data model

`users` stores all three roles. `courses` own `exams`; `examiners` links examiners to exams. `rubrics` define exam criteria. `slots` belong to an exam and an examiner. `bookings` connect a student to a slot and preserve cancellation history. `scores` hold one mark and feedback entry per rubric criterion for a booking.

## Scope

The implementation focuses on the core demo workflow. It does not include email, downloadable scorecards, public APIs, advanced search, slot rescheduling, detailed audit logging, or production deployment security. Bootstrap styling is loaded from its public CDN; an internet connection is needed for Bootstrap styling, while the application logic and database run locally.
