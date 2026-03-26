<?php
session_start(); // بدء الجلسة

// ======== اتصال SQLite ========
$db = new SQLite3('database.db'); // ضع هنا اسم ملف قاعدة البيانات

// ======== استلام بيانات النموذج ========
$email = $_POST['email'] ?? '';
$password = $_POST['password'] ?? '';

// ======== تحضير الاستعلام ========
$stmt = $db->prepare('SELECT id, email, password FROM users WHERE email = :email');
$stmt->bindValue(':email', $email, SQLITE3_TEXT);
$result = $stmt->execute();
$user = $result->fetchArray(SQLITE3_ASSOC);

// ======== التحقق من بيانات تسجيل الدخول ========
if (!$user || !password_verify($password, $user['password'])) {
    // إعادة التوجيه مع رسالة خطأ
    header('Location: login.php?error=invalid');
    exit;
}

// ======== تسجيل الجلسة ========
$_SESSION['user_id'] = $user['id'];
$_SESSION['email'] = $user['email'];

// ======== إعادة التوجيه للصفحة المحمية ========
header('Location: dashboard.php');
exit;
?>
