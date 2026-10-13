# Attendix

Attendix is a Flask and Supabase PostgreSQL attendance app. Only the super admin signs in. The admin registers each student with face photos and an assigned location. A student opens the public page, presses **Mark attendance**, and the browser captures a face photo and GPS position. The server identifies the registered face, checks the assigned geo-fence and schedule, and saves one attendance record per student per day.

## Run

The supplied Supabase connection is in the local Git-ignored `.env`. The tables and first admin account were already created. The generated admin login is in the Git-ignored `.admin-credentials` file.

```powershell
.\MyEnv\Scripts\python.exe -m pip install -r requirements.txt
$env:FLASK_APP = 'app:create_app'
.\MyEnv\Scripts\python.exe -m flask run
```

Open `http://127.0.0.1:5000` for the public attendance page. Select **Super admin login** for setup. The admin should change the temporary password from Profile. Camera and GPS work on localhost or HTTPS, not a plain HTTP connection to another device.

For a fresh database, run `flask init-db`, set `ADMIN_EMAIL` and a strong `ADMIN_PASSWORD` in the shell, then run `flask create-admin`. Never commit `.env` or `.admin-credentials`.

## Set up attendance

1. Super admin adds a location with coordinates, radius and schedule. **Use current position** can fill the location coordinates while standing at the site.
2. Super admin registers each student with a name, assigned location and three camera photos. Students receive no account credentials.
3. Student opens the public page and presses **Mark attendance**. The camera opens, the browser requests location, and the captured image is submitted for server-side matching. A recognized student inside their assigned radius and working hours is recorded. An outside-range attempt displays **You are not in the range of your assigned location.**
4. Super admin sees saved records in History and Reports. Student records can be deactivated or their face reference replaced from Students.

## Rules and limits

- One record per student per day is enforced by a database unique constraint. Late arrivals after the configured grace period are marked late. Unrecognized faces, disabled students, invalid schedules, missing GPS and outside-range attempts do not create attendance.
- OpenCV Haar detection and LBPH matching use three processed face crops per student. This is suitable for an academic prototype. It has no liveness detection, and a photo or replay attack is possible. Use consent and stronger biometric controls for real deployment.
- Browser GPS can be spoofed by a compromised device. Production deployment needs HTTPS and `SESSION_COOKIE_SECURE=true`.
- Student records retain internal database fields for compatibility with the existing schema; no student password or email is shown or accepted by the login page. Only active admin accounts can sign in.
- Attendance history displays UTC check-in time. Schedule checks use `APP_TIMEZONE` (default Asia/Kolkata).

## Tests

```powershell
.\MyEnv\Scripts\python.exe -m pytest -q
```

Tests use temporary SQLite and do not write to Supabase.
