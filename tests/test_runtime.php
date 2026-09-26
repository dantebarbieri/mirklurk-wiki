<?php
define('MEDIAWIKI', true);
define('CACHE_DB', 1);
$loaded = [];
function wfLoadSkin(string $name): void {
    $GLOBALS['loaded'][] = $name;
}
function wfLoadExtension(string $name): void {
    $GLOBALS['loaded'][] = $name;
}
function check(bool $condition, string $message): void {
    if (!$condition) {
        throw new RuntimeException($message);
    }
}
function rejects(callable $operation): void {
    try {
        $operation();
    } catch (RuntimeException $error) {
        return;
    }
    throw new RuntimeException('Expected explicit configuration failure.');
}

$temporary = sys_get_temp_dir() . '/mirklurk-unit-' . bin2hex(random_bytes(8));
mkdir($temporary, 0700);
$files = [];
try {
    foreach (['DB_PASSWORD', 'SECRET_KEY', 'UPGRADE_KEY', 'CAPTCHA_QUESTIONS'] as $name) {
        $path = $temporary . '/' . $name;
        $files[] = $path;
        file_put_contents($path, bin2hex(random_bytes(40)));
        putenv('MW_' . $name . '_FILE=' . $path);
    }
    file_put_contents(end($files), json_encode(['Synthetic <question>' => ['Synthetic answer']]));
    putenv('MW_SERVER_URL=https://wiki.example.invalid');
    putenv('MW_TRUSTED_PROXY_CIDRS=192.0.2.10,2001:db8::/64');
    putenv('MW_READ_ONLY=Maintenance unit test');
    require __DIR__ . '/../deploy/LocalSettings.template.php';
    check($wgServer === 'https://wiki.example.invalid' && $wgCookieSecure, 'HTTPS configuration mismatch.');
    check($wgGroupPermissions['*']['read'] && $wgGroupPermissions['*']['createaccount'], 'Public access missing.');
    check(!$wgGroupPermissions['*']['edit'] && $wgGroupPermissions['user']['edit'], 'Editing policy mismatch.');
    check(!$wgEnableUploads && !$wgEnableEmail, 'Disabled functionality unexpectedly enabled.');
    check(!$wgAllowCopyUploads && !$wgAllowExternalImages, 'Remote image access unexpectedly enabled.');
    check($wgUseImageMagick === true, 'CLI-imported images require the installed ImageMagick renderer.');
    check($wgImageMagickConvertCommand === '/usr/bin/convert', 'Pinned image renderer path mismatch.');
    check($wgMainCacheType === CACHE_DB && $wgMainStash === CACHE_DB, 'Throttles require shared cache.');
    check($wgCaptchaTriggers['createaccount'] && $wgCaptchaTriggers['addurl'], 'CAPTCHA trigger missing.');
    check(isset($wgCaptchaQuestions['Synthetic &lt;question&gt;']), 'Question HTML was not escaped.');
    check($wgReadOnly === 'Maintenance unit test', 'Edit freeze not applied.');
    check($wgAccountCreationThrottle[0]['count'] === 3, 'Signup rate limit missing.');
    check(count($wgCdnServersNoPurge) === 2, 'Trusted proxy configuration missing.');
    check(in_array('ConfirmEdit/QuestyCaptcha', $loaded, true), 'CAPTCHA extension not loaded.');
    check(in_array('ParserFunctions', $loaded, true), 'Selective canonical views require ParserFunctions.');

    foreach (['http://public.example.invalid', 'https://wiki.example.invalid/', 'https://wiki.example.invalid?x=1'] as $url) {
        putenv('MW_SERVER_URL=' . $url);
        rejects('mirklurkServer');
    }
    putenv('MW_SERVER_URL=http://localhost:8089');
    check(mirklurkServer() === 'http://localhost:8089', 'Loopback development origin rejected.');
    putenv('MW_SERVER_URL');
    rejects('mirklurkServer');
    foreach (['0.0.0.0/0', '::/0', 'not-an-address', '192.0.2.1/33'] as $proxy) {
        putenv('MW_TRUSTED_PROXY_CIDRS=' . $proxy);
        rejects('mirklurkTrustedProxies');
    }
    foreach (['{}', '[]', '{"question":[]}', '{"question":[""]}', '{"question":"not a list"}', 'invalid'] as $invalid) {
        file_put_contents(end($files), $invalid);
        rejects('mirklurkQuestions');
    }
    file_put_contents($files[0], '');
    rejects(static fn() => mirklurkSecret('MW_DB_PASSWORD_FILE', 16));
    putenv('MW_DB_PASSWORD_FILE=' . $temporary . '/missing');
    rejects(static fn() => mirklurkSecret('MW_DB_PASSWORD_FILE', 16));
    echo "Runtime configuration tests passed.\n";
} finally {
    foreach ($files as $path) {
        unlink($path);
    }
    rmdir($temporary);
}
