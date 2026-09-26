<?php
if (!defined('MEDIAWIKI')) {
    exit;
}
require_once __DIR__ . '/mirklurk-runtime.php';

$wgSitename = 'MirkLurk Wiki';
$wgMetaNamespace = 'MirkLurk_Wiki';
$wgServer = mirklurkServer();
$wgCanonicalServer = $wgServer;
$wgScriptPath = '';
$wgArticlePath = '/index.php?title=$1';
$wgLanguageCode = 'en';

$wgDBtype = 'mysql';
$wgDBserver = mirklurkEnv('MW_DB_SERVER', 'mirklurk-db');
$wgDBname = mirklurkEnv('MW_DB_NAME', 'mirklurk');
$wgDBuser = mirklurkEnv('MW_DB_USER', 'mirklurk');
$wgDBpassword = mirklurkSecret('MW_DB_PASSWORD_FILE', 16);
$wgDBprefix = '';
$wgSecretKey = mirklurkSecret('MW_SECRET_KEY_FILE', 64);
$wgUpgradeKey = mirklurkSecret('MW_UPGRADE_KEY_FILE', 32);
$wgMainCacheType = CACHE_DB;
$wgSessionCacheType = CACHE_DB;
$wgMainStash = CACHE_DB;
$wgCookieSecure = str_starts_with($wgServer, 'https://');
$wgCookieHttpOnly = true;
$wgCdnServersNoPurge = mirklurkTrustedProxies();

$wgGroupPermissions['*']['read'] = true;
$wgGroupPermissions['*']['createaccount'] = true;
$wgGroupPermissions['*']['edit'] = false;
$wgGroupPermissions['*']['createpage'] = false;
$wgGroupPermissions['*']['createtalk'] = false;
$wgGroupPermissions['*']['writeapi'] = false;
$wgGroupPermissions['user']['edit'] = true;
$wgGroupPermissions['user']['createpage'] = true;
$wgGroupPermissions['user']['createtalk'] = true;
$wgGroupPermissions['user']['writeapi'] = true;
$wgEnableUploads = false;
$wgAllowCopyUploads = false;
$wgAllowExternalImages = false;
$wgUseImageMagick = true;
$wgImageMagickConvertCommand = '/usr/bin/convert';
$wgEnableEmail = false;
$wgEnableUserEmail = false;
$wgEmailConfirmToEdit = false;
$wgPasswordResetRoutes = ['username' => false, 'email' => false];
$wgRightsText = '';
$wgRightsUrl = '';
$wgRightsIcon = '';

$wgRateLimits['edit'] = ['user' => [10, 60], 'newbie' => [3, 60], 'ip' => [15, 60]];
$wgRateLimits['createaccount'] = ['ip' => [3, 3600]];
$wgRateLimits['badcaptcha'] = ['ip' => [10, 60], 'user' => [10, 60]];
$wgRateLimits['sendemail'] = ['user' => [0, 86400]];
$wgAccountCreationThrottle = [
    ['count' => 3, 'seconds' => 3600],
    ['count' => 10, 'seconds' => 86400],
];
$wgPasswordAttemptThrottle = [
    ['count' => 5, 'seconds' => 300],
    ['count' => 30, 'seconds' => 86400],
];

wfLoadSkin('Vector');
$wgDefaultSkin = 'vector-2022';
wfLoadExtension('ParserFunctions');
wfLoadExtension('ConfirmEdit');
wfLoadExtension('ConfirmEdit/QuestyCaptcha');
$wgCaptchaClass = 'QuestyCaptcha';
$wgCaptchaQuestions = mirklurkQuestions();
$wgCaptchaTriggers['createaccount'] = true;
$wgCaptchaTriggers['badlogin'] = true;
$wgCaptchaTriggers['badloginperuser'] = true;
$wgCaptchaTriggers['addurl'] = true;
$wgCaptchaTriggers['edit'] = false;
$wgCaptchaTriggers['create'] = false;

$readOnly = mirklurkEnv('MW_READ_ONLY', '');
if ($readOnly !== '') {
    $wgReadOnly = $readOnly;
}
