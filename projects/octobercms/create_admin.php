<?php
require __DIR__ . '/bootstrap/autoload.php';
$app = require_once __DIR__ . '/bootstrap/app.php';

use Illuminate\Support\Facades\Hash;
use Backend\Models\User;

$app->make('Illuminate\Contracts\Console\Kernel')->bootstrap();

// Check if user table exists
if (!\Schema::hasTable('backend_users')) {
    echo "User table does not exist.\n";
    exit(1);
}

// Check if admin user already exists
$admin = User::where('login', 'admin')->first();
if ($admin) {
    echo "Admin user already exists.\n";
    echo "Username: " . $admin->login . "\n";
    echo "Email: " . $admin->email . "\n";
    exit(0);
}

// Create admin user
try {
    $user = new User();
    $user->first_name = 'Administrator';
    $user->last_name = 'User';
    $user->login = 'admin';
    $user->email = 'admin@example.com';
    $user->password = 'admin123';
    $user->password_confirmation = 'admin123';
    $user->is_superuser = true;
    $user->is_activated = true;
    $user->activated_at = now();
    $user->save();
    
    echo "Admin user created successfully!\n";
    echo "Username: admin\n";
    echo "Password: admin123\n";
    echo "Email: admin@example.com\n";
} catch (Exception $e) {
    echo "Error creating admin user: " . $e->getMessage() . "\n";
    exit(1);
}
?>