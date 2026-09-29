<?php
define('MEDIAWIKI', true);
require_once '/var/www/html/mirklurk-runtime.php';

header('Content-Type: text/plain; charset=UTF-8');
header('Cache-Control: public, max-age=300');
header('X-Content-Type-Options: nosniff');

echo "User-agent: *\n";
echo "Disallow: /api.php\n";
echo "Disallow: /rest.php\n";
echo "Disallow: /load.php\n";
echo "Disallow: /index.php?search=\n";
echo "Disallow: /index.php?title=Special%3ASearch\n";
echo "Disallow: /index.php?title=Special:Search\n";
echo "Disallow: /w/Special:Search\n";
echo "Disallow: /w/Special%3ASearch\n";
echo "\nSitemap: " . mirklurkServer() . "/sitemap.xml\n";
