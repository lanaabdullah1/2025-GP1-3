<?php
session_start();

if (!isset($_SESSION['userID'])) {
    header("Location: log.php");
    exit;
}
?>
