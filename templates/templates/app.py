from flask import Flask, render_template, request, redirect, url_for, session

app = Flask(__name__)
app.secret_key = "eyecept_secret_key"


# الصفحة الرئيسية
@app.route('/')
def home():
    return render_template('index.html')


# صفحة تسجيل الدخول
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        # تسجيل دخول تجريبي
        if email == "test@example.com" and password == "123456":
            session['user'] = email
            return redirect(url_for('dashboard'))
        else:
            return render_template('login.html', error="Wrong login")

    return render_template('login.html')


# صفحة processing login إذا تحتاجينها
@app.route('/processing-login')
def processing_login():
    return render_template('processing_login.html')


# صفحة dashboard
@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('login'))
    return render_template('dashboard.html')


# صفحة redirect login إذا تبينها
@app.route('/redirect-login')
def redirect_login():
    return redirect(url_for('login'))


# تسجيل الخروج
@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('home'))


if __name__ == '__main__':
    app.run(debug=True)
