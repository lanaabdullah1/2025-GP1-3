<?php
require_once 'connection.php';
session_start();

$email = $_POST['email'];
$password = $_POST['password'];

$stmt = $conn->prepare("SELECT userID, password FROM user WHERE email = ?");
$stmt->bind_param("s", $email);
$stmt->execute();
$result = $stmt->get_result();
$user = $result->fetch_assoc();

if (!$user || !password_verify($password, $user['password'])) {
    header("Location: log.php?error=invalid");
    exit;
}

$_SESSION['userID'] = $user['userID'];
header("Location: dashboard.php");
exit;
?>
