from flask import Flask, render_template, request, redirect, url_for

app = Flask(__name__)

# الصفحة الرئيسية (login)
@app.route('/')
def home():
    return render_template('login.html')


# route لمعالجة تسجيل الدخول
@app.route('/login', methods=['POST'])
def login():
    email = request.form.get('email')
    password = request.form.get('password')

    # مؤقت (تجربة فقط)
    if email == "test@example.com" and password == "123456":
        return redirect('/dashboard')
    else:
        return "Wrong login"


# صفحة dashboard (تجريبية)
@app.route('/dashboard')
def dashboard():
    return "<h1>Welcome to Dashboard</h1>"


if __name__ == '__main__':
    app.run(debug=True)
  from flask import Flask, render_template

app = Flask(__name__)

@app.route('/')
def processing_login():
    return render_template('processing_login.html')

if __name__ == '__main__':
    app.run(debug=True)
  
from flask import Flask, redirect, url_for

app = Flask(__name__)

@app.route('/logout')
def logout():
    return redirect(url_for('home'))  # يحول مباشرة للصفحة الرئيسية

@app.route('/')
def home():
    return "<h1>Home Page</h1>"

if __name__ == '__main__':
    app.run(debug=True)
  from flask import Flask, render_template

app = Flask(__name__)

# صفحة redirect (تعرض الصفحة)
@app.route('/redirect-login')
def redirect_login():
    return render_template('redirect_login.html')


# صفحة login
@app.route('/login')
def login():
    return render_template('log.html')


if __name__ == '__main__':
    app.run(debug=True)
  from flask import Flask, redirect, url_for

app = Flask(__name__)

@app.route('/redirect-login')
def redirect_login():
    return redirect(url_for('login'))

@app.route('/login')
def login():
    return render_template('log.html')

if __name__ == '__main__':
    app.run(debug=True)
