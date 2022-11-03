import json
import pyrebase
import uuid
import parser
import reminder
import hashlib
from flask import Flask, jsonify, make_response, request, abort, send_from_directory
from flask_apscheduler import APScheduler
import os

app = Flask(__name__, static_folder="build") # for prod

# Connect to Firebase Realtime DB
firebase = pyrebase.initialize_app(json.load(open('secrets.json')))
# Authenticate Firebase tables
db = firebase.database()


# Enable CORS only in development
if app.debug:
    from flask_cors import CORS
    cors = CORS(app)
else:
    # schedule process to send notifications 
    scheduler = APScheduler()
    scheduler.init_app(app)
    scheduler.start()

    @scheduler.task('cron', id='send_notif', hour='8')
    def send_notification():
        """Schedule notifications to be sent out at 8 am for all users"""
        users = db.child("users").get().val()
        for _,info in users.items():
            # Added logic to enable/disable notifications globally
            if "courses" in info and info["courses"] and "notification" in info and info["notification"]:
                reminder.send_email(info.get("name"), info.get("email", "courseofactoin@gmail.com"), info["courses"])

def get_user(utorid):
    """
    Check the HTTP headers for user's utorid and return the hash for each user
    This will create a user profile in Firebase for first time use
    """
    if not utorid and app.debug: # for local dev we set it to a defined test user
        user = "UuT5Mb7uJKO8N6mTTv9LuyCexgl1"
    elif not utorid:
        abort(401, description="User not authenticated") 
    else:
        user = hashlib.sha256(utorid.encode("utf-8")).hexdigest()
    # check existing users
    user_exists = db.child("users").child(user).get()
    if not user_exists.val():
        # register user in firebase
        try:
            db.child("users").child(user).set({"name": request.headers["Http-Cn"], "email": request.headers["Http-Mail"], "courses": []})
        except:
            abort(401, description="Unable to create user") # redirect page since app is not accessible
    return user

@app.route("/coa/")
def index():
    # format_headers = lambda d: '\n'.join(k + ": " +v for k, v in d.items())
    # data = jsonify(data=(request.method, request.url, "\n\n"+format_headers(request.headers)))
    # code above will print all request header for future additions + security 
    
    # redirect user to the app 
    response = make_response()
    response.headers['location'] = "/coa/app/" 
    return response, 302

@app.route('/coa/app/', defaults={'path': ''})
@app.route("/coa/app/<path:path>")
def send_app(path):
    """
    Serve static files for the frontend app
    """
    user = get_user(request.headers.get("Utorid"))
    if path != "" and os.path.exists(app.static_folder + '/' + path):
        return send_from_directory(app.static_folder, path)
    else:
        return send_from_directory(app.static_folder, 'index.html')

@app.route('/coa/api/application-start', methods=["GET"])
def application_start():
    """
    Function to retrieve all courses for the student
    """
    user = get_user(request.headers.get("Utorid"))
    try:
        userInfo = db.child('users').child(user).get().val()
        # Removing things we only need for seniding reminders
        userInfo.pop("email")
        userInfo.pop("name")
        return make_response(jsonify(userInfo), 200)
    except:
        return make_response(jsonify(message='Server error. Please load again'), 500)

@app.route('/coa/api/update-user-notification', methods=["POST"])
def update_user_notification():
    """
    Function to retrieve all courses for the student
    """
    user = get_user(request.headers.get("Utorid"))
    notification = request.json.get('notification', None)
    if not (request.json) or not (notification == 0 or notification == 1):
        return bad_request('Error missing required course information')
    try:
        userInfo = db.child('users').child(user).child("notification").set(request.json["notification"])
        return make_response(jsonify(userInfo), 200)
    except:
        return make_response(jsonify(message='Server error. Please load again'), 500)


@app.route('/coa/api/add-course', methods=["POST"])
def add_course():
    """
    Function to create a new course and add it for that specific user 
    """
    user = get_user(request.headers.get("Utorid"))
    if not (request.json) or not(request.json.get('code', None)):
        return bad_request('Error missing required course information')

    #make sure the course code is unique
    existing_course = db.child('users').child(user).child("courses").order_by_child("code").equal_to(request.json['code']).get().val()
    if existing_course:
        return make_response(jsonify(message='Error course already exists'), 403)

    try:
        db.child('users').child(user).child("courses").child(request.json['code']).set(request.json)
        # TOOD: add this later
        # db.child('Courses').child(request.form['courseCode']).set(request.json)
        return jsonify(messge="success")
    except:
        return make_response(jsonify(message='Error creating course'), 401)

@app.route('/coa/api/delete-course', methods=["POST"])
def delete_course():
    """
    Function to delete given course and from that specific user 
    """
    # getting user from request
    user = get_user(request.headers.get("Utorid"))
    # checking request has everything needed
    if not(request.json.get('code', None)):
        return bad_request('Error missing required course information')
    try:
        courses = db.child('users').child(user).child("courses").get().val()
        if request.json['code'] in courses:
            db.child('users').child(user).child("courses").child(request.json['code']).remove()
            return jsonify(messge="success")
        return make_response(jsonify(message="Course does not exist for current user"), 401)
    except:
        return make_response(jsonify(message='Error deleting course'), 401)
    
@app.route('/coa/api/update-assessments', methods=["POST"])
def update_assessment():
    """
    This function updates the assessments for each a specific user
    """
    # getting user from request
    user = get_user(request.headers.get("Utorid"))
    # checking request has everything needed
    if not(request.json.get('code', None)) or not (request.json.get('assessments', None)) or (request.json.get('currMark', None) == None):
        return bad_request('Error missing required course information')
    
    req_code = request.json['code']
    req_assessments = request.json['assessments']
    req_currMark = request.json['currMark']
    existing_course = db.child('users').child(user).child("courses").order_by_child("code").equal_to(req_code).get().val()
    # checking if the course exists
    if not existing_course:
        return make_response(jsonify(message="Course you are trying to update doesn't exist"), 401)

    try: 
        # setting assessment info in the database
        db.child('users').child(user).child("courses").child(req_code).update({"assessments": req_assessments, "currMark": req_currMark})
        return jsonify(message="success")
    except:
        return make_response(jsonify(message='Error updating assessments'), 401)

@app.route('/coa/api/update-course', methods=["PATCH"])
def update_course():
    """
    This function updates the course's expected mark and familiarity
    """
    # getting user from request
    user = get_user(request.headers.get("Utorid"))
    # checking request has everything needed
    if not request.json.get('expectedMark', None) or not request.json.get('familiarity', None) or not request.json.get('code', None):
        return bad_request('Error missing required course information')
        
    req_code = request.json['code']
    req_expectedMark = request.json['expectedMark']
    req_familiarity = request.json['familiarity']
    req_notification =  request.json.get('notification', 1)
    existing_course = db.child('users').child(user).child("courses").order_by_child("code").equal_to(req_code).get().val()
    # checking if the course exists
    if not existing_course:
        return make_response(jsonify(message="Course you are trying to update doesn't exist"), 401)
    
    try: 
        # setting assessment info in the database
        db.child('users').child(user).child("courses").child(req_code).update({"familiarity": req_familiarity, "expectedMark": req_expectedMark, "notification": req_notification})
        return jsonify(message="success")
    except:
        return make_response(jsonify(message='Error updating assessments'), 401)


@app.route('/coa/api/parse-syllabus', methods=["POST"])
def parse_syllabus():
    # get and save the file
    if 'file' not in request.files:
        return bad_request("Bad Request")
    file = request.files['file']
    if file.filename == '':
        return bad_request("File not attached")
    # create unique name for the file
    filename = uuid.uuid4()
    file_path = '/tmp' + os.sep + str(filename)
    # save file
    file.save(file_path)
    # parse assessments
    parsed_assessments = parser.extract_info(file_path)
    os.remove(file_path)
    # check if parsed correctly
    if isinstance(parsed_assessments, int):
        return bad_request("The syllabus format is not supported. Please enter your assessments manually.")
    return { "assessments": parsed_assessments }

@app.errorhandler(500)
def app_error(e):
    return make_response("Application error! Please try again later!"), 500

def bad_request(mess: str):
    return make_response(jsonify(message=mess), 400)
