<?php
declare(strict_types=1);

use MediaWiki\CommentStore\CommentStoreComment;
use MediaWiki\Content\ContentHandler;
use MediaWiki\Context\RequestContext;
use MediaWiki\Deferred\DeferredUpdates;
use MediaWiki\Maintenance\Maintenance;
use MediaWiki\MediaWikiServices;
use MediaWiki\Permissions\PermissionManager;
use MediaWiki\Revision\RevisionRecord;
use MediaWiki\Revision\SlotRecord;
use MediaWiki\Title\Title;
use Wikimedia\Rdbms\IDBAccessObject;
use Wikimedia\Rdbms\IDatabase;

if (PHP_SAPI !== 'cli') {
    http_response_code(404);
    exit;
}
require_once (getenv('MW_INSTALL_PATH') ?: '/var/www/html') . '/maintenance/Maintenance.php';

class NativePublicationError extends RuntimeException {
}

class NativePublication extends Maintenance {
    private string $stage = 'validated';

    public function __construct() {
        parent::__construct();
        $this->addDescription('Publish exactly one manifest-bound revision without merge or retries.');
        $this->addOption('manifest', 'Private canonical v1 run manifest', true, true);
        $this->addOption('request', 'Private canonical v1 operation request', true, true);
    }

    protected function checkpoint(string $stage): void {
        // Disposable tests subclass this boundary; no production fault switches.
    }

    private function check(bool $condition, string $code): void {
        if (!$condition) {
            throw new NativePublicationError($code);
        }
    }

    private function fields(array $value, string $keys): void {
        $actual = array_keys($value);
        $expected = explode(' ', $keys);
        sort($actual);
        sort($expected);
        $this->check($actual === $expected, 'invalid-fields');
    }

    private function hex($value, int $length = 64): void {
        $this->check(is_string($value) && preg_match('/^[0-9a-f]{' . $length . '}$/D', $value) === 1,
            'invalid-hash-or-nonce');
    }

    private function positive($value): void {
        $this->check(is_int($value) && $value > 0, 'invalid-positive-integer');
    }

    private function canonical($value): string {
        $sort = function ($item) use (&$sort) {
            if (is_object($item)) {
                $values = get_object_vars($item);
                ksort($values, SORT_STRING);
                return (object)array_map($sort, $values);
            }
            if (is_array($item)) {
                return array_map($sort, $item);
            }
            $this->check(is_string($item) || is_int($item) || is_bool($item) || $item === null,
                'unsupported-json-value');
            $this->check(!is_int($item) || abs($item) <= 9007199254740991, 'noninteroperable-json-integer');
            return $item;
        };
        return json_encode($sort($value), JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES
            | JSON_UNESCAPED_LINE_TERMINATORS | JSON_THROW_ON_ERROR);
    }

    private function read(string $path): array {
        $this->check(is_file($path) && !is_link($path) && filesize($path) <= 32 * 1024 * 1024,
            'invalid-input-file');
        $raw = file_get_contents($path);
        $this->check($raw !== false, 'input-read-failed');
        $value = json_decode($raw, false, 512, JSON_THROW_ON_ERROR);
        $this->check(is_object($value) && $this->canonical($value) === $raw, 'noncanonical-json');
        return [json_decode($raw, true, 512, JSON_THROW_ON_ERROR), hash('sha256', $raw)];
    }

    private function title(array $row): Title {
        $this->check(isset($row['namespace'], $row['title']) && is_int($row['namespace'])
            && in_array($row['namespace'], [0, 14], true) && is_string($row['title']), 'invalid-title');
        $title = Title::newFromText($row['title']);
        $this->check($title !== null && !$title->isExternal() && !$title->hasFragment()
            && $title->getNamespace() === $row['namespace'] && $title->getPrefixedText() === $row['title'],
            'noncanonical-title');
        return $title;
    }

    private function tuple(array $row): void {
        $this->fields($row, 'page_id revision_id raw_sha256');
        if ($row['page_id'] === 0) {
            $this->check($row['revision_id'] === 0 && $row['raw_sha256'] === null, 'invalid-absence');
        } else {
            $this->positive($row['page_id']);
            $this->positive($row['revision_id']);
            $this->hex($row['raw_sha256']);
        }
    }

    private function raw(RevisionRecord $revision): string {
        $content = $revision->getContent(SlotRecord::MAIN, RevisionRecord::RAW);
        $this->check($content !== null && $content->getModel() === CONTENT_MODEL_WIKITEXT, 'non-wikitext-main-slot');
        return $content->serialize();
    }

    private function guard(array $expected, ?RevisionRecord $revision): void {
        $this->tuple($expected);
        $this->check(($revision ? $revision->getPageId() : 0) === $expected['page_id']
            && ($revision ? $revision->getId() : 0) === $expected['revision_id']
            && ($revision ? hash('sha256', $this->raw($revision)) : null) === $expected['raw_sha256'],
            'expected-parent-mismatch');
    }

    private function state(Title $title, RevisionRecord $revision): array {
        $db = MediaWikiServices::getInstance()->getConnectionProvider()->getPrimaryDatabase();
        $actorId = $db->newSelectQueryBuilder()->select('rev_actor')->from('revision')
            ->where(['rev_id' => $revision->getId()])->caller(__METHOD__)->fetchField();
        return ['namespace' => $title->getNamespace(), 'title' => $title->getPrefixedText(),
            'page_id' => $revision->getPageId(), 'revision_id' => $revision->getId(),
            'parent_id' => $revision->getParentId(), 'raw_sha256' => hash('sha256', $this->raw($revision)),
            'actor_id' => (int)$actorId, 'comment' => $revision->getComment(RevisionRecord::RAW)->text];
    }

    private function emit(array $event): void {
        $this->output(json_encode($event, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_THROW_ON_ERROR) . "\n");
        flush();
    }

    public function execute() {
        [$manifest, $manifestHash] = $this->read($this->getOption('manifest'));
        [$request, $requestHash] = $this->read($this->getOption('request'));
        $this->fields($manifest, 'schema_version kind run_nonce source runtime operator binding_sha256 corpora '
            . 'prerequisites_sha256 operations preserved');
        $this->fields($request, 'schema_version kind manifest_sha256 run_nonce index attempt operation_nonce '
            . 'worker desired_text prerequisites prerequisite_evidence_sha256 previous_accepted_sha256');
        $this->check($manifest['schema_version'] === 1 && $request['schema_version'] === 1
            && $manifest['kind'] === 'native-publication-manifest'
            && $request['kind'] === 'native-publication-request', 'unsupported-schema');
        $this->check($request['manifest_sha256'] === $manifestHash
            && $request['run_nonce'] === $manifest['run_nonce'], 'manifest-binding-mismatch');
        $this->hex($manifest['run_nonce'], 32);
        $this->fields($manifest['source'], 'head_sha tree_sha');
        foreach ($manifest['source'] as $value) {
            $this->hex($value, 40);
        }
        $this->fields($manifest['runtime'], 'mediawiki_version primitive_sha256 fingerprint_sha256');
        $this->check(MW_VERSION === '1.43.9' && $manifest['runtime']['mediawiki_version'] === MW_VERSION
            && $manifest['runtime']['primitive_sha256'] === hash_file('sha256', __FILE__), 'runtime-mismatch');
        $this->hex($manifest['runtime']['fingerprint_sha256']);
        $this->fields($manifest['corpora'], 'previous_authored baseline authored desired');
        foreach ([...array_values($manifest['corpora']), $manifest['binding_sha256'],
            $manifest['prerequisites_sha256'], $request['previous_accepted_sha256'],
            $request['prerequisite_evidence_sha256']] as $value) {
            $this->hex($value);
        }
        $this->positive($request['index']);
        $this->positive($request['attempt']);
        $this->check($request['attempt'] <= 999, 'attempt-limit-exceeded');
        $this->fields($request['worker'], 'nonce identity');
        $this->hex($request['worker']['nonce'], 32);
        $this->check(is_string($request['worker']['identity'])
            && preg_match('/^[A-Za-z0-9_.:-]{1,160}$/D', $request['worker']['identity']) === 1, 'invalid-worker');
        $seen = $nonces = [];
        $this->check(is_array($manifest['operations']) && array_is_list($manifest['operations'])
            && count($manifest['operations']) >= $request['index'], 'unknown-operation');
        foreach ($manifest['operations'] as $offset => $row) {
            $this->fields($row, 'index operation_nonce namespace title expected desired_sha256 prerequisites_sha256 prerequisites');
            $this->check($row['index'] === $offset + 1, 'operation-order-mismatch');
            $title = $this->title($row);
            $this->check(!isset($seen[$title->getPrefixedText()]) && !isset($nonces[$row['operation_nonce']]),
                'duplicate-operation');
            $seen[$title->getPrefixedText()] = $nonces[$row['operation_nonce']] = true;
            $this->hex($row['operation_nonce'], 32);
            $this->tuple($row['expected']);
            $this->hex($row['desired_sha256']);
            $this->hex($row['prerequisites_sha256']);
            $this->check($row['desired_sha256'] !== $row['expected']['raw_sha256'], 'dispatched-storage-noop');
            $this->check(is_array($row['prerequisites']) && array_is_list($row['prerequisites']),
                'invalid-static-prerequisites');
            $owners = [];
            foreach ($row['prerequisites'] as $owner) {
                $this->fields($owner, 'namespace title raw_sha256');
                $ownerTitle = $this->title($owner);
                $this->hex($owner['raw_sha256']);
                $this->check(!isset($owners[$ownerTitle->getPrefixedText()]), 'duplicate-prerequisite');
                $owners[$ownerTitle->getPrefixedText()] = true;
            }
        }
        $this->check(is_array($manifest['preserved']) && array_is_list($manifest['preserved']), 'invalid-preserved-list');
        foreach ($manifest['preserved'] as $row) {
            $this->fields($row, 'namespace title page_id revision_id raw_sha256');
            $preservedTitle = $this->title($row);
            $this->check(!isset($seen[$preservedTitle->getPrefixedText()]), 'duplicate-preserved-title');
            $seen[$preservedTitle->getPrefixedText()] = true;
            $this->positive($row['page_id']);
            $this->tuple(array_intersect_key($row, array_flip(['page_id', 'revision_id', 'raw_sha256'])));
        }
        $operation = $manifest['operations'][$request['index'] - 1];
        $title = $this->title($operation);
        $this->check($request['operation_nonce'] === $operation['operation_nonce']
            && is_string($request['desired_text'])
            && hash('sha256', $request['desired_text']) === $operation['desired_sha256'], 'desired-binding-mismatch');
        $this->fields($manifest['operator'], 'id name actor_id');
        $this->positive($manifest['operator']['id']);
        $this->positive($manifest['operator']['actor_id']);
        $services = MediaWikiServices::getInstance();
        $db = $services->getConnectionProvider()->getPrimaryDatabase();
        $userRow = $db->newSelectQueryBuilder()->select(['user_name', 'user_editcount'])->from('user')
            ->where(['user_id' => $manifest['operator']['id']])->caller(__METHOD__)->fetchRow();
        $actor = $db->newSelectQueryBuilder()->select(['actor_user', 'actor_name'])->from('actor')
            ->where(['actor_id' => $manifest['operator']['actor_id']])->caller(__METHOD__)->fetchRow();
        $this->check($userRow !== false && $actor !== false && $userRow->user_editcount !== null
            && $userRow->user_name === $manifest['operator']['name']
            && (int)$actor->actor_user === $manifest['operator']['id']
            && $actor->actor_name === $manifest['operator']['name'], 'existing-operator-mismatch');
        $user = $services->getUserFactory()->newFromId($manifest['operator']['id']);
        $this->check($user->getName() === $manifest['operator']['name'], 'operator-name-mismatch');
        $services->getUserEditTracker()->setCachedUserEditCount($user, (int)$userRow->user_editcount);
        RequestContext::getMain()->setUser($user);
        $stat = file_get_contents('/proc/self/stat');
        $this->check($stat !== false, 'worker-identity-unavailable');
        $statFields = explode(' ', substr($stat, strrpos($stat, ')') + 2));
        $start = ['pid' => getmypid(), 'boot_id' => trim(file_get_contents('/proc/sys/kernel/random/boot_id')),
            'process_start_ticks' => (int)$statFields[19],
            'db_connection_id' => (int)$db->newSelectQueryBuilder()->select('CONNECTION_ID()')->caller(__METHOD__)->fetchField()];
        $event = ['schema_version' => 1, 'kind' => 'native-publication-start', 'request_sha256' => $requestHash,
            'manifest_sha256' => $manifestHash, 'worker' => $request['worker'], 'start' => $start];
        $this->emit($event);
        $atomic = false;
        try {
            $this->check(!$services->getReadOnlyMode()->isReadOnly(), 'worker-read-only');
            $permissions = $services->getPermissionManager();
            $this->check(!$permissions->isBlockedFrom($user, $title, false), 'operator-blocked');
            foreach ($operation['expected']['page_id'] === 0 ? ['edit', 'create'] : ['edit'] as $action) {
                $this->check($permissions->getPermissionStatus($action, $user, $title,
                    PermissionManager::RIGOR_SECURE)->isGood(), 'permission-denied-' . $action);
            }
            $this->check(is_array($request['prerequisites']) && array_is_list($request['prerequisites'])
                && count($request['prerequisites']) === count($operation['prerequisites']), 'prerequisite-count-mismatch');
            $store = $services->getRevisionStore();
            foreach ($request['prerequisites'] as $offset => $owner) {
                $this->fields($owner, 'namespace title page_id revision_id raw_sha256');
                $binding = $operation['prerequisites'][$offset];
                $this->fields($binding, 'namespace title raw_sha256');
                $this->check($binding === array_intersect_key($owner, $binding), 'prerequisite-binding-mismatch');
                $this->positive($owner['page_id']);
                $ownerTitle = $this->title($owner);
                $this->guard(array_intersect_key($owner, array_flip(['page_id', 'revision_id', 'raw_sha256'])),
                    $store->getRevisionByTitle($ownerTitle, 0, IDBAccessObject::READ_LATEST));
            }
            $this->checkpoint('before-parent');
            $page = $services->getWikiPageFactory()->newFromTitle($title);
            $updater = $page->newPageUpdater($user);
            $parent = $updater->grabParentRevision();
            $this->stage = 'parent';
            $this->guard($operation['expected'], $parent);
            $this->checkpoint('after-parent');
            // One operation, not a batch transaction. Never perform conflict resolution.
            $db->startAtomic(__METHOD__, IDatabase::ATOMIC_CANCELABLE);
            $atomic = true;
            $updater->setContent(SlotRecord::MAIN,
                ContentHandler::makeContent($request['desired_text'], $title, CONTENT_MODEL_WIKITEXT));
            $this->stage = 'saving';
            $revision = $updater->saveRevision(CommentStoreComment::newUnsavedComment(
                'native-publication/v1:' . $requestHash),
                $operation['expected']['page_id'] === 0 ? EDIT_NEW : EDIT_UPDATE);
            $this->stage = 'saved';
            $this->check($updater->getStatus()->isOK() && $updater->wasRevisionCreated()
                && $revision !== null, 'save-failed-or-null');
            $saved = $this->state($title, $revision);
            $this->check($saved['parent_id'] === $operation['expected']['revision_id']
                && $saved['revision_id'] > $operation['expected']['revision_id'] && $saved['page_id'] > 0
                && $saved['raw_sha256'] === $operation['desired_sha256']
                && $saved['actor_id'] === $manifest['operator']['actor_id']
                && $saved['comment'] === 'native-publication/v1:' . $requestHash
                && ($operation['expected']['page_id'] === 0 || $saved['page_id'] === $operation['expected']['page_id']),
                'saved-revision-mismatch');
            $this->checkpoint('before-commit');
            $db->endAtomic(__METHOD__);
            $atomic = false;
            $services->getDBLoadBalancerFactory()->commitPrimaryChanges(__METHOD__);
            $this->stage = 'committed';
            $this->checkpoint('after-commit');
            DeferredUpdates::doUpdates();
            $services->getDBLoadBalancerFactory()->commitPrimaryChanges(__METHOD__);
            $fresh = $store->getRevisionByTitle($this->title($operation), 0, IDBAccessObject::READ_LATEST);
            $this->check($fresh !== null && $this->state($title, $fresh) === $saved, 'fresh-revision-mismatch');
            $this->stage = 'verified';
            $this->emit([...$event, 'kind' => 'native-publication-result', 'outcome' => 'committed',
                'stage' => $this->stage, 'revision' => $saved, 'error' => null]);
        } catch (Throwable $error) {
            if ($atomic) {
                $db->cancelAtomic(__METHOD__);
            }
            $this->emit([...$event, 'kind' => 'native-publication-result', 'outcome' => 'error',
                'stage' => $this->stage, 'revision' => null,
                'error' => $error instanceof NativePublicationError ? $error->getMessage() : get_class($error)]);
            // Even an error is not a noncommit certificate. The coordinator must prove quiescence.
            $this->fatalError('Native publication stopped; reconcile the durable intent.', 1);
        }
    }
}

$maintClass = NativePublication::class;
require_once RUN_MAINTENANCE_IF_MAIN;
