<?php
// Disposable integration for one synthetic table; never loaded by the production image.

use MediaWiki\MediaWikiServices;
use MediaWiki\Title\Title;

final class PrototypeCargo {
    public const TABLE = 'PrototypeRecords';
    public const READER = 'prototype-cargo-reader';
    public const OWNER = 'prototype-cargo-owner';

    public static function register(Parser $parser): void {
        $parser->setFunctionHook('prototype_query', static function (Parser $parser, ...$args) {
            $parser->getOutput()->setPageProperty(self::READER, self::TABLE);
            return CargoQuery::run($parser, 'tables=' . self::TABLE, ...$args);
        });
        $parser->setFunctionHook('prototype_owner', static function (Parser $parser) {
            $parser->getOutput()->setPageProperty(self::OWNER, '1');
            return '';
        });
    }

    public static function queueRefresh(): void {
        MediaWikiServices::getInstance()->getJobQueueGroup()->push(
            new PrototypeCargoRefreshJob(Title::makeTitle(NS_MAIN, 'Prototype index'), [])
        );
    }

    public static function linksComplete($update): void {
        $output = $update->getParserOutput();
        if ($output->getPageProperty(self::OWNER) !== null ||
            array_key_exists(self::OWNER, $update->getRemovedProperties() ?? [])) {
            self::queueRefresh();
        }
    }

    public static function restored($page): void {
        MediaWikiServices::getInstance()->getJobQueueGroup()->push(
            new PrototypeCargoRestoreJob(Title::newFromPageIdentity($page), ['pageId' => $page->getId()])
        );
    }

    public static function moved($old, $new): void {
        self::queueRefresh();
    }

    public static function deleted($page): void {
        self::queueRefresh();
    }
}

final class PrototypeCargoRefreshJob extends Job {
    public function __construct($title, array $params = []) {
        parent::__construct('prototypeCargoRefresh', $title, $params);
    }

    public function run() {
        $db = CargoUtils::getMainDBForRead();
        $readers = $db->select('page_props', ['pp_page'],
            ['pp_propname' => PrototypeCargo::READER, 'pp_value' => PrototypeCargo::TABLE], __METHOD__);
        $ids = [];
        foreach ($readers as $row) {
            $ids[] = (int)$row->pp_page;
        }
        if (count($ids) > 200) {
            throw new RuntimeException('Disposable reader bound exceeded; no partial invalidation attempted.');
        }
        foreach ($ids as $id) {
            $page = MediaWikiServices::getInstance()->getWikiPageFactory()->newFromID($id);
            if ($page) {
                $page->doPurge();
            }
        }
        return true;
    }
}

final class PrototypeCargoRestoreJob extends Job {
    public function __construct($title, array $params = []) {
        parent::__construct('prototypeCargoRestore', $title, $params);
    }

    public function run() {
        $services = MediaWikiServices::getInstance();
        $pageId = (int)$this->params['pageId'];
        $db = CargoUtils::getMainDBForWrite();
        $lock = $db->getScopedLockAndFlush('prototype-cargo-restore-' . $pageId, __METHOD__, 10);
        if (!$lock) {
            throw new RuntimeException('Could not lock the disposable restore job.');
        }
        for ($attempt = 0; $attempt < 3; $attempt++) {
            $page = $services->getWikiPageFactory()->newFromID($pageId);
            if (!$page) {
                PrototypeCargo::queueRefresh();
                return true;
            }
            $latestId = (int)$db->selectField('page', 'page_latest', ['page_id' => $pageId], __METHOD__);
            $revision = $services->getRevisionStore()->getRevisionById($latestId);
            if (!$revision) {
                throw new RuntimeException('Current restored revision could not be read.');
            }
            $content = $revision->getContent('main');
            if ($content->getModel() !== CONTENT_MODEL_WIKITEXT) {
                return true;
            }
            // Cargo's stock replaceOldRows job only clears the main table, not list rows.
            CargoHooks::deletePageFromSystem($pageId);
            try {
                CargoStore::$settings = ['origin' => 'template', 'dbTableName' => PrototypeCargo::TABLE];
                $output = CargoUtils::parsePageForStorage($page->getTitle(), $content->getText());
                if ($output->getPageProperty('CargoStorageError') !== null) {
                    throw new RuntimeException('Cargo rejected restored current-revision data.');
                }
            } finally {
                CargoStore::$settings = [];
            }
            $latest = $db->selectField('page', 'page_latest', ['page_id' => $pageId], __METHOD__);
            if ((int)$latest === $revision->getId()) {
                PrototypeCargo::queueRefresh();
                return true;
            }
        }
        throw new RuntimeException('Owner kept changing during restore; retry explicitly through the job queue.');
    }
}

$wgHooks['ParserFirstCallInit'][] = [PrototypeCargo::class, 'register'];
$wgExtensionMessagesFiles['PrototypeCargo'] = __DIR__ . '/prototype_cargo_magic.php';
$wgHooks['LinksUpdateComplete'][] = [PrototypeCargo::class, 'linksComplete'];
$wgHooks['PageUndeleteComplete'][] = [PrototypeCargo::class, 'restored'];
$wgHooks['PageMoveComplete'][] = [PrototypeCargo::class, 'moved'];
$wgHooks['PageDeleteComplete'][] = [PrototypeCargo::class, 'deleted'];
$wgJobClasses['prototypeCargoRefresh'] = PrototypeCargoRefreshJob::class;
$wgJobClasses['prototypeCargoRestore'] = PrototypeCargoRestoreJob::class;
