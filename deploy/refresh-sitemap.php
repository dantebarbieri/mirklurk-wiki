<?php
require_once '/var/www/html/maintenance/Maintenance.php';

final class MirklurkRefreshSitemap extends Maintenance {
    public function __construct() {
        parent::__construct();
        $this->addDescription('Atomically publish the native public-article sitemap.');
    }

    public function execute() {
        $config = $this->getConfig();
        if (!$this->getServiceContainer()->getPermissionManager()->isEveryoneAllowed('read')
            || $config->get('DefaultRobotPolicy') !== 'index,follow'
            || $config->get('ArticleRobotPolicies') !== []
            || $config->get('ExemptFromUserRobotsControl') !== []
            || array_intersect_key($config->get('NamespaceRobotPolicies'), array_flip([NS_MAIN, NS_CATEGORY]))
            || $config->get('SitemapNamespaces') !== [NS_MAIN, NS_CATEGORY]) {
            $this->fatalError('Sitemap requires public reading and the reviewed main/category indexing policy. '
                . 'Core generateSitemap does not honor custom per-title/namespace robot policies; review before refreshing.');
        }
        $root = '/var/lib/mirklurk-sitemap';
        $lock = fopen("$root/refresh.lock", 'c');
        if (!$lock || !flock($lock, LOCK_EX | LOCK_NB)) {
            $this->fatalError('Sitemap storage is unavailable or a refresh is already running.');
        }
        $identifier = 'wiki-' . bin2hex(random_bytes(12));
        $stage = "$root/$identifier";
        if (!mkdir($stage, 0700)) {
            $this->fatalError('Unable to create private sitemap staging directory.');
        }
        try {
            $generator = $this->createChild('GenerateSitemap', '/var/www/html/maintenance/generateSitemap.php');
            foreach ([
                'fspath' => $stage, 'urlpath' => '/', 'identifier' => $identifier,
                'compress' => 'no', 'skip-redirects' => true,
            ] as $name => $value) {
                $generator->setOption($name, $value);
            }
            $generator->execute();
            $files = glob("$stage/*.xml");
            $index = "$stage/sitemap-index-$identifier.xml";
            if (count($files) < 2 || !is_file($index)) {
                throw new RuntimeException('Native sitemap output is empty or incomplete; previous sitemap preserved.');
            }
            $origin = $config->get('CanonicalServer');
            foreach ($files as $file) {
                $xml = new DOMDocument();
                if (!$xml->load($file, LIBXML_NONET)
                    || $xml->documentElement->namespaceURI !== 'http://www.sitemaps.org/schemas/sitemap/0.9'
                    || !in_array($xml->documentElement->localName, ['urlset', 'sitemapindex'], true)) {
                    throw new RuntimeException('Native sitemap is not valid sitemap XML; previous sitemap preserved.');
                }
                foreach ($xml->getElementsByTagName('loc') as $location) {
                    if (!str_starts_with($location->textContent, $origin . '/')) {
                        throw new RuntimeException('Sitemap URL has an unexpected origin; previous sitemap preserved.');
                    }
                }
                if (!chmod($file, 0644)) {
                    throw new RuntimeException('Cannot set sitemap read permissions; previous sitemap preserved.');
                }
            }
            foreach ($files as $file) {
                if ($file !== $index && !rename($file, "$root/public/" . basename($file))) {
                    throw new RuntimeException('Cannot publish sitemap shard; previous index preserved.');
                }
            }
            // Unique shards first, then one atomic rename on the same filesystem.
            if (!rename($index, "$root/public/sitemap.xml")) {
                throw new RuntimeException('Cannot publish sitemap index; previous index preserved.');
            }
            $this->output("Published $origin/sitemap.xml\n");
        } finally {
            foreach (glob("$stage/*.xml") as $file) {
                unlink($file);
            }
            rmdir($stage);
            flock($lock, LOCK_UN);
            fclose($lock);
        }
    }
}

$maintClass = MirklurkRefreshSitemap::class;
require_once RUN_MAINTENANCE_IF_MAIN;
