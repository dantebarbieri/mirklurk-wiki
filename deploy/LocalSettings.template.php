<?php
if (!defined('MEDIAWIKI')) {
    exit;
}
require_once __DIR__ . '/mirklurk-runtime.php';
require_once __DIR__ . '/mirklurk-metadata.php';
require_once __DIR__ . '/mirklurk-editing.php';

$wgSitename = 'MirkLurk Wiki';
$wgMetaNamespace = 'MirkLurk_Wiki';
$wgServer = mirklurkServer();
$wgCanonicalServer = $wgServer;
$wgScriptPath = '';
$wgArticlePath = '/w/$1';
$wgLanguageCode = 'en';
$wgEnableCanonicalServerLink = true;
$wgSitemapNamespaces = [NS_MAIN, NS_CATEGORY];
// Let authors opt articles out of indexing as well as category pages.
$wgExemptFromUserRobotsControl = [];
$wgHooks['OutputPageAfterGetHeadLinksArray'][] = MirklurkMetadata::class . '::onHeadLinks';

// Core normalizes titles, but leaves already-normalized index.php views alone.
$wgHooks['MediaWikiPerformAction'][] = static function (
    \MediaWiki\Output\OutputPage $output,
    \Article $article,
    \MediaWiki\Title\Title $title,
    \MediaWiki\User\User $user,
    \MediaWiki\Request\WebRequest $request
): bool {
    $url = $request->getRequestURL();
    if (!in_array($request->getMethod(), ['GET', 'HEAD'], true)
        || parse_url($url, PHP_URL_PATH) !== '/index.php'
        || !preg_match('/\A(?:title=[^&;]+(?:&action=view)?|action=view&title=[^&;]+)\z/',
            parse_url($url, PHP_URL_QUERY) ?? '')
        || $title->isSpecialPage() || $title->isExternal()
        || $request->getRawVal('action', 'view') !== 'view'
    ) {
        return true;
    }
    // Keep wiki redirect pages as URLs, including their normal redirected-from notice.
    $requestedTitle = $article->getRedirectedFrom() ?: $title;
    $output->redirect($requestedTitle->getFullURL(), 301);
    return false;
};

$logo = mirklurkImageUrl('MW_LOGO_URL');
$logoIcon = mirklurkImageUrl('MW_LOGO_ICON_URL');
$favicon = mirklurkImageUrl('MW_FAVICON_URL');
if (($logo === '') !== ($logoIcon === '')) {
    throw new RuntimeException('MW_LOGO_URL and MW_LOGO_ICON_URL must be configured together.');
}
if ($logo !== '') {
    $wgLogo = $logo;
    $wgLogos = ['1x' => $logo, 'icon' => $logoIcon];
}
if ($favicon !== '') {
    $wgFavicon = $favicon;
}

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
$wgVectorResponsive = true;
wfLoadExtension('ParserFunctions');
wfLoadExtension('Scribunto');
$wgScribuntoDefaultEngine = 'luastandalone';
// MediaWiki 1.43 bundles both and uses its integrated PHP Parsoid client; no RESTBase service.
wfLoadExtension('TemplateData');
wfLoadExtension('VisualEditor');
$wgVisualEditorUseSingleEditTab = false;
$wgVisualEditorDisableForAnons = true;
$wgDefaultUserOptions['visualeditor-autodisable'] = 0;
$wgDefaultUserOptions['visualeditor-betatempdisable'] = 0;
$wgDefaultUserOptions['visualeditor-newwikitext'] = 0;
$wgVisualEditorAvailableNamespaces['Help'] = true;
$wgVisualEditorAvailableNamespaces['Template'] = false;
$wgHooks['VisualEditorBeforeEditor'][] = MirklurkEditing::class . '::onVisualEditorBeforeEditor';
$wgHooks['ApiCheckCanExecute'][] = MirklurkEditing::class . '::onApiCheckCanExecute';
$wgHooks['EditPage::showEditForm:initial'][] = MirklurkEditing::class . '::onEditPageShowEditFormInitial';
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
