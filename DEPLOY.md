# Putting ClosureCheck online so it opens on a phone

A phone only allows the camera and GPS on a secure (https) link, so the app must be
online (or tunnelled) before you can test it on a phone. 

## Option A: PythonAnywhere (free, keeps your database and photos)
1. Make a free account at pythonanywhere.com. Your app address will be
   https://YOURNAME.pythonanywhere.com
2. Files tab -> upload the zip -> open a Bash console and run:  unzip closurecheck_mobile.zip
3. Web tab -> "Add a new web app" -> Manual configuration -> pick a recent Python 3 version.
4. In the Web tab set "Source code" to /home/YOURNAME/closurecheck
5. Click the WSGI configuration file link and replace everything with:

       import os, sys
       path = "/home/YOURNAME/closurecheck"
       if path not in sys.path:
           sys.path.insert(0, path)
       os.environ["SECRET_KEY"] = "type-a-long-random-sentence-here"
       os.environ["OFFICER_CODE"] = "choose-your-own-officer-code"
       os.environ["COOKIE_SECURE"] = "1"
       from app import app as application

6. Press the green Reload button, then open https://YOURNAME.pythonanywhere.com on your phone.
7. In the phone browser menu choose "Add to Home screen" / "Install app".

(PythonAnywhere's menus can change a little; the idea stays the same.)

## Option B: quick test from your laptop with a tunnel (ngrok)
1. Run the app:           python app.py
2. In a second terminal:  ngrok http 5000   (needs a free ngrok account)
3. Open the https link ngrok prints on your phone.

## Testing on a laptop
Citizen pages are blocked on laptops on purpose. To test the code on a laptop webcam anyway:
    set ALLOW_DESKTOP=1        (Windows cmd)
    python app.py

## Accounts (login)
- Citizens sign up on the Sign up page. They can file complaints and add after-photos to THEIR OWN complaints only.
- Department officers also use the Sign up page, choose "Department officer" and type the OFFICER_CODE.
  Officers see all complaints and the Department page, and mark complaints resolved.
- IMPORTANT: change OFFICER_CODE in the WSGI file before you share the link. If you do not set one,
  the built-in demo code is "demo-officer", which anyone reading the code could guess.
- Passwords are stored hashed. Five wrong passwords for one username lock it for 10 minutes.
- Complaints saved before accounts existed have no owner: officers see them, citizens do not.
- Tip for judges: make one demo citizen and one demo officer account with throw-away passwords, and
  only share those with the people who need them.

## Changing the background picture
The artwork is static/img/hero.svg (an illustration made for this project).
To use a real photo instead (best: a photo of a road you took yourself):
1. Save it as static/img/hero.jpg (landscape, under 500 KB).
2. In static/style.css replace the two places that say  url("img/hero.svg")  with  url("img/hero.jpg").
Keep the dark gradient in front of it so the text stays readable.
