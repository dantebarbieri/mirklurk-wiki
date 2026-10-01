<?php
if (PHP_SAPI !== 'cli') {
    http_response_code(404);
    exit(1);
}
require_once '/var/www/html/mirklurk-runtime.php';

$options = getopt('', ['admin:', 'password-file:']);
if (!isset($options['admin'], $options['password-file']) || count($options) !== 2) {
    fwrite(STDERR, "Usage: install.php --admin NAME --password-file MOUNTED_FILE\n");
    exit(2);
}

try {
    $server = mirklurkServer();
    mirklurkQuestions();
    mirklurkSecret('MW_SECRET_KEY_FILE', 64);
    mirklurkSecret('MW_UPGRADE_KEY_FILE', 32);
    putenv('MIRKLURK_INSTALL_PASSWORD_FILE=' . $options['password-file']);
    mirklurkSecret('MIRKLURK_INSTALL_PASSWORD_FILE', 16);
    $dbHost = mirklurkEnv('MW_DB_SERVER', 'mirklurk-db');
    $dbName = mirklurkEnv('MW_DB_NAME', 'mirklurk');
    $dbUser = mirklurkEnv('MW_DB_USER', 'mirklurk');
    mysqli_report(MYSQLI_REPORT_ERROR | MYSQLI_REPORT_STRICT);
    $database = new mysqli($dbHost, $dbUser, mirklurkSecret('MW_DB_PASSWORD_FILE', 16), $dbName);
    $result = $database->query('SHOW TABLES');
    if ($result->num_rows !== 0) {
        throw new RuntimeException('Installation refused: the selected database is not empty. Use update for upgrades.');
    }
    $database->close();
} catch (mysqli_sql_exception $error) {
    fwrite(STDERR, "Installation preflight failed: database connection/query unsuccessful.\n");
    exit(1);
} catch (RuntimeException $error) {
    fwrite(STDERR, "Installation preflight failed: " . $error->getMessage() . "\n");
    exit(1);
}

if (getenv('MIRKLURK_INSTALL_STAGE') !== 'core') {
    // The core installer only sees its generated settings, so the baked settings' extensions
    // (Echo, Linter, DiscussionTools) create their tables in a follow-up schema update.
    $runChild = static function (array $command): int {
        $process = proc_open($command, [STDIN, STDOUT, STDERR], $pipes);
        return is_resource($process) ? proc_close($process) : 1;
    };
    putenv('MIRKLURK_INSTALL_STAGE=core');
    $status = $runChild([PHP_BINARY, __FILE__,
        '--admin', $options['admin'], '--password-file', $options['password-file']]);
    putenv('MIRKLURK_INSTALL_STAGE');
    if ($status !== 0) {
        fwrite(STDERR, "Installation failed; the extension schema update was not run.\n");
        exit($status);
    }
    // A brand-new wiki has no readers to protect, and update.php refuses read-only mode.
    putenv('MW_READ_ONLY');
    $status = $runChild([PHP_BINARY, '/var/www/html/maintenance/run.php', 'update', '--quick']);
    if ($status !== 0) {
        fwrite(STDERR, "Installation completed, but the extension schema update failed; rerun update.\n");
    }
    exit($status);
}

$temporary = sys_get_temp_dir() . '/mirklurk-install-' . bin2hex(random_bytes(12));
if (!mkdir($temporary, 0700)) {
    fwrite(STDERR, "Installation could not create its private temporary directory.\n");
    exit(1);
}
register_shutdown_function(static function () use ($temporary): void {
    $generated = $temporary . '/LocalSettings.php';
    if (is_file($generated) && !unlink($generated)) {
        fwrite(STDERR, "WARNING: remove the installer container; temporary configuration cleanup failed.\n");
    }
    if (!rmdir($temporary)) {
        fwrite(STDERR, "WARNING: remove the installer container; temporary directory cleanup failed.\n");
    }
});

// The upstream installer must not mistake the baked runtime template for an installed wiki.
define('MW_CONFIG_FILE', $temporary . '/LocalSettings.php');
$argv = [
    '/var/www/html/maintenance/run.php', 'install',
    '--dbtype=mysql', '--dbserver=' . $dbHost, '--dbname=' . $dbName, '--dbuser=' . $dbUser,
    '--dbpassfile=' . mirklurkEnv('MW_DB_PASSWORD_FILE'),
    '--passfile=' . $options['password-file'], '--server=' . $server,
    '--scriptpath=', '--lang=en', '--skins=Vector', '--confpath=' . $temporary,
    'MirkLurk Wiki', $options['admin'],
];
$argc = count($argv);
$_SERVER['argv'] = $argv;
$_SERVER['argc'] = $argc;
require '/var/www/html/maintenance/run.php';
