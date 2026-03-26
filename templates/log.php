<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>Login - Eyecept</title>
<link rel="stylesheet" href="css/shared.css">
<link rel="stylesheet" href="css/log.css">
</head>

<body>

<div id="header-placeholder"></div>

<main class="login-main">
  <div class="login-box">

    <img src="images/logo.png" class="login-logo">
    <h2>Login</h2>

    <?php if (isset($_GET['error'])): ?>
      <p style="color:red;">
        <?php
        if ($_GET['error'] == 'empty') echo "Fill all fields";
        elseif ($_GET['error'] == 'invalid') echo "Wrong login";
        ?>
      </p>
    <?php endif; ?>

    <form class="login-form" action="login_process.php" method="POST">
      <input type="email" name="email" placeholder="Email">
      <input type="password" name="password" placeholder="Password">
	  <p class="forgot-password" id="forgotPassword">Forgot Password?</p>
      <button type="submit">Login</button>
    </form>

  </div>
</main>

<div id="footer-placeholder"></div>

<script src="js/include.js"></script>
</body>
</html>
