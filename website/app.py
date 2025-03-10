from flask import (
    Flask,
    render_template,
    request,
    session,
    redirect,
    url_for,
    send_from_directory,
)
import os
from flask_socketio import SocketIO, emit

import requests 
import json

my_user_name = ""
my_client_id = "D0F8359CBAF0597B2DCDC2EE9EE41E96960E810B8F6FDE8068789CF97B56820C"
my_client_secret = "0482DC03638C7AF2DE3D4D3E402AE6FC0447D11C11DC89E469AFAE8DD980F61E"
my_redirect_uri = "http://127.0.0.1:5001/get_code"

homeappliance_data = {}
coffee_maker = {}

app = Flask(__name__)
app.config["SECRET_KEY"] = "bla"
UPLOAD_FOLDER = "./uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

socketio = SocketIO(app)

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)


@app.route("/login", methods=["GET", "POST"])
def login():
    global my_user_name

    print("login")
    if request.method == "POST":
        username = request.form["username"]
        my_user_name = username
        session["username"] = username

        return redirect(url_for("home"))
    else:
        return render_template("login.html")


@app.route("/")
@app.route("/home")
def home():
    print(f"home {session['username']} {my_user_name}")

    if "username" not in session and my_user_name == None:
        return redirect(url_for("login"))
    elif "username" in session:
       return render_template("index.html", username=session["username"])
    else:
       return render_template("index.html", username=my_user_name)


@app.route("/app_start", methods=["GET", "'POST"])
def process_app_start():
    print("app start")
    return render_template("app_start.html")


@app.route("/get_code", methods=["GET", "POST"])
def get_authorization_code():
    global homeconnect_access_data
    global homeappliance_data
    global coffee_maker

    r = request.url.split("code=")[1]
   ## r = r[:-6] + "=="
    print(f"code: {r}")

    url = "https://simulator.home-connect.com/security/oauth/token"
    payload = 'grant_type=authorization_code' + '&' + 'code=' + r + '&' + 'client_id=' + my_client_id + '&' + 'client_secret=' + my_client_secret+ '&' + 'redirect_uri=' + my_redirect_uri
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}

    response = requests.request("POST", url, headers=headers, data=payload)
    homeconnect_access_data = json.loads(response.text)

    if "error" in homeconnect_access_data:
        print(homeconnect_access_data)
    else:
        print("access token received:")
        print(homeconnect_access_data["access_token"])
        url = "https://simulator.home-connect.com/api/homeappliances"

        payload = {}
        headers = {
            'Authorization': f'Bearer {homeconnect_access_data["access_token"]}',
            'Accept': 'application/vnd.bsh.sdk.v1+json'
        }

        response = requests.request("GET", url, headers=headers, data=payload)
        homeappliance_data = json.loads(response.text)

        if len(homeappliance_data['data']['homeappliances']) > 0:
            for appliance in homeappliance_data['data']['homeappliances']:
                print(f"new appliance: {appliance['type']}")
                if appliance['type'] == 'CoffeeMaker':
                    coffee_maker = appliance
        else:
            print("No home appliances connected.")

    return redirect(url_for("login"))


@app.route("/message", methods=["POST"])
def handle_synthetic_message():
    global my_user_name

    sender = request.form["username"]
    if sender == 'user':
        sender = my_user_name

    socketio.emit(
        "chat_message",
        {
            "sender": sender,
            "message": request.form["message"],
        })

    return render_template("index.html", username=request.form["username"])

@app.route("/coffee_settings", methods=["POST"])
def control_coffee_maker():
    global coffee_maker
    global homeconnect_access_data
    global my_user_name

    types = {'Espresso' : 'ConsumerProducts.CoffeeMaker.Program.Beverage.Espresso',
             'Cappuccino' : 'ConsumerProducts.CoffeeMaker.Program.Beverage.Cappuccino',
             'Americano' : 'ConsumerProducts.CoffeeMaker.Program.CoffeeWorld.Americano',
             'Latte Macchiato' : 'ConsumerProducts.CoffeeMaker.Program.Beverage.LatteMacchiato'}

    strength_levels = {'very mild' : 'ConsumerProducts.CoffeeMaker.EnumType.BeanAmount.VeryMild',
                       'mild' : 'ConsumerProducts.CoffeeMaker.EnumType.BeanAmount.Mild',
                       'normal' : 'ConsumerProducts.CoffeeMaker.EnumType.BeanAmount.Normal',
                       'strong' : 'ConsumerProducts.CoffeeMaker.EnumType.BeanAmount.Strong',
                       'very strong' : 'ConsumerProducts.CoffeeMaker.EnumType.BeanAmount.VeryStrong',
                       'double shot' : 'ConsumerProducts.CoffeeMaker.EnumType.BeanAmount.DoubleShot',
                       'double shot +' : 'ConsumerProducts.CoffeeMaker.EnumType.BeanAmount.DoubleShotPlus',
                       'double shot ++' : 'ConsumerProducts.CoffeeMaker.EnumType.BeanAmount.DoubleShotPlusPlus' }

    temp_levels = {  'normal' : 'ConsumerProducts.CoffeeMaker.EnumType.CoffeeTemperature.90C',
                     'high' : 'ConsumerProducts.CoffeeMaker.EnumType.CoffeeTemperature.94C',
                     'very high' : 'ConsumerProducts.CoffeeMaker.EnumType.CoffeeTemperature.95C'}

    setting_type = request.form['type']
    setting_strength = request.form['strength']
    setting_quantity = request.form['quantity']
    setting_temp = request.form['temp']

    print(request.form)
    print(coffee_maker)
    if len(coffee_maker) > 0:
        url = f"https://simulator.home-connect.com/api/homeappliances/{coffee_maker['haId']}/programs/active"

        payload = json.dumps({
            "data": {
                "key": types[setting_type],
                "options": [
                    {
                        "key": "ConsumerProducts.CoffeeMaker.Option.BeanAmount",
                        "value": strength_levels[setting_strength]
                    },
                    {
                        "key": "ConsumerProducts.CoffeeMaker.Option.CoffeeTemperature",
                        "value": temp_levels[setting_temp],
                        "unit": "enum"
                    },
                    {
                        "key": "ConsumerProducts.CoffeeMaker.Option.FillQuantity",
                        "value": setting_quantity,
                        "unit": "ml"
                    }
                ]
            }
        })
        print(payload)
        headers = {
#            'Authorization': 'Bearer   eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCIsImtpZCI6IjE5IiwieC1yZWciOiJTSU0iLCJ4LWVudiI6IlBSRCJ9.eyJleHAiOjE3MzM0OTc5OTgsInNjb3BlIjpbIklkZW50aWZ5QXBwbGlhbmNlIiwiQ29mZmVlTWFrZXIiXSwiYXpwIjoiRDBGODM1OUNCQUYwNTk3QjJEQ0RDMkVFOUVFNDFFOTY5NjBFODEwQjhGNkZERTgwNjg3ODlDRjk3QjU2ODIwQyIsImF1ZCI6IkQwRjgzNTlDQkFGMDU5N0IyRENEQzJFRTlFRTQxRTk2OTYwRTgxMEI4RjZGREU4MDY4Nzg5Q0Y5N0I1NjgyMEMiLCJwcm0iOltdLCJpc3MiOiJldTpzaW06b2F1dGg6MSIsImp0aSI6IjgyOWQzNDExLTFlZTMtNDVkOC1iMmIwLTNlMTE0NDljMWE5OSIsImlhdCI6MTczMzQxMTU5OH0.fdP4_8nTT4RHiVhPQkj43WapgbbfaORoFNnfGwXTWKj50hq5Bs5UnbUq5tsEO5RXD71p6WmVj8MCVAj7O_gLECVaRD7m7F9ZtXrusc7PYHKUeK6jEAzxryi3D5nPEZ-Ez6LkuMfvYzeysG3iJ79rZwrS1O7Kfcs7I_M6q-XuXeyT7_yQcxE173PFD-SH-Z8HUDyCb3gi4pHGHbAIkAWp3PFwvRGj8lQuIJyv-VZkp65GQoqCIL85ggYM_Q7qWSTywU13b2O0Z6o2C-Q9G29uYSn8ZNw4mFUuGymaSYip-r0F1rozTf7N6KC-uLbx8p8TaR4nOUYghSrWwEn_BCqr2w',
            'Authorization': f'Bearer   {homeconnect_access_data["access_token"]}',
            'Accept': 'application/vnd.bsh.sdk.v1+json',
            'Content-Type': 'application/vnd.bsh.sdk.v1+json'
        }

        response = requests.request("PUT", url, headers=headers, data=payload)
        print(response.text)
    else:
        print("Coffeemaker not connected.")

    return render_template("index.html", username=my_user_name)

@app.route("/log_belief_state", methods=["POST"])
def belief_state_logger():
    global my_user_name

    user_belief = request.form
    print(f"belief state: {user_belief}")

    return render_template("index.html", username=my_user_name)

@socketio.on("connect")
def handle_connect():
    session["client_id"] = request.sid
    emit("connection_response", {"client_id": request.sid})

    print("connect")
    if "username" in session:
        username = session["username"]
        socketio.emit(
            "chat_message",
            {"sender": "System", "message": f"{username} has logged in"},
            skip_sid=request.sid,
        )

@app.route("/logout")
def logout():
    if "username" in session:
        session.pop("username", None)
        session.pop("client_id", None)

    return redirect(url_for("login"))

@socketio.on("disconnect")
def handle_disconnect():
    if "username" in session:
        username = session["username"]
        emit(
            "chat_message",
            {"sender": "System", "message": f"{username} has left the chat"},
            broadcast=True,
        )
        session.pop("username", None)
        session.pop("client_id", None)

@socketio.on("message")
def handle_message(data):
    sender = session.get("username")  # Get the username from the session
    message = data["message"]

    emit(
        "chat_message",
        {
            "sender": sender,
            "message": message,
            "client_id": session.get("client_id"),
        },
        broadcast=True,
    )

@socketio.on("upload")
def handle_upload(data):
    file = data["file"]
    filename = data["name"]
    filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)

    try:
        with open(filepath, "wb") as f:
            f.write(file)
    except Exception as e:
        print("Failed to save file", e)
    # Broadcast the URL of the uploaded file to all other users
    file_url = f"/uploads/{filename}"
    emit("file_uploaded", {"filename": filename, "file_url": file_url}, broadcast=True)


@app.route("/uploads/<path:filename>", methods=["GET", "POST"])
def download_file(filename):
    return send_from_directory(
        app.config["UPLOAD_FOLDER"], filename, as_attachment=True
    )


if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5001, debug=True)