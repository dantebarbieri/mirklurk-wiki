<?php
namespace MediaWiki\Title {
    class Title {
        public function __construct(private int $namespace, private string $dbKey) {
        }
        public static function makeTitle(int $namespace, string $dbKey): self {
            return new self($namespace, $dbKey);
        }
        public function getText(): string {
            return str_replace('_', ' ', $this->dbKey);
        }
    }
}

namespace {
    use MediaWiki\Title\Title;

    define('MEDIAWIKI', true);
    const NS_MAIN = 0;
    $GLOBALS['pages'] = [
        'Worn_Socks', 'Decent_Socks', 'Fine_Wool_Socks', 'Worn_Boots', 'Socket_wrench',
        'Bloodsocks', 'Items', 'Mirkfang', 'Giant_Mirkfang', 'Mirkfang_Matriarch',
    ];
    $GLOBALS['queries'] = [];

    class SearchSuggestion {
        public function __construct(public Title $title) {
        }
    }

    class SearchSuggestionSet {
        private array $suggestions = [];
        public function __construct(array $suggestions, private bool $hasMore = false) {
            foreach ($suggestions as $suggestion) {
                $this->append($suggestion);
            }
        }
        public static function fromTitles(array $titles): self {
            return new self(array_map(static fn(Title $title) => new SearchSuggestion($title), $titles));
        }
        public function append(SearchSuggestion $suggestion): void {
            foreach ($this->suggestions as $existing) {
                if ($existing->title->getText() === $suggestion->title->getText()) {
                    return;
                }
            }
            $this->suggestions[] = $suggestion;
        }
        public function getSuggestions(): array {
            return $this->suggestions;
        }
        public function hasMoreResults(): bool {
            return $this->hasMore;
        }
        public function getSize(): int {
            return count($this->suggestions);
        }
        public function texts(): array {
            return array_map(static fn($s) => $s->title->getText(), $this->suggestions);
        }
    }

    class FakeQuery {
        private string $needle = '';
        public function select(array $fields): self {
            return $this;
        }
        public function from(string $table): self {
            if ($table !== 'page') {
                throw new RuntimeException('Completion must read page titles.');
            }
            return $this;
        }
        public function where(array $conditions): self {
            if ($conditions['page_is_redirect'] !== 0 || $conditions['page_namespace'] !== [NS_MAIN]) {
                throw new RuntimeException('Completion must search non-redirect article titles.');
            }
            preg_match("/LIKE '%(.*)%'/", end($conditions), $match);
            $this->needle = $match[1] ?? '';
            $GLOBALS['queries'][] = $this->needle;
            return $this;
        }
        public function limit(int $limit): self {
            return $this;
        }
        public function caller(string $caller): self {
            return $this;
        }
        public function fetchResultSet(): array {
            $rows = [];
            foreach ($GLOBALS['pages'] as $page) {
                if (str_contains(mb_strtolower($page), $this->needle)) {
                    $rows[] = (object)['page_namespace' => NS_MAIN, 'page_title' => $page];
                }
            }
            return $rows;
        }
    }

    class FakeDatabase {
        public function newSelectQueryBuilder(): FakeQuery {
            return new FakeQuery();
        }
        public function anyString(): string {
            return '%';
        }
        public function buildLike(string ...$parts): string {
            return " LIKE '" . implode('', $parts) . "'";
        }
    }

    class FakeProvider {
        public function getReplicaDatabase(): FakeDatabase {
            return new FakeDatabase();
        }
    }

    class SearchMySQL {
        public array $namespaces = [NS_MAIN];
        protected int $limit = 10;
        protected int $offset = 0;
        public function __construct(protected FakeProvider $dbProvider) {
        }
        public function setLimitOffset(int $limit, int $offset = 0): void {
            $this->limit = $limit;
            $this->offset = $offset;
        }
        protected function completionSearchBackend($search) {
            $titles = [];
            foreach ($GLOBALS['pages'] as $page) {
                if (stripos($page, str_replace(' ', '_', $search)) === 0) {
                    $titles[] = Title::makeTitle(NS_MAIN, $page);
                }
            }
            return SearchSuggestionSet::fromTitles(array_slice($titles, 0, $this->limit));
        }
        public function complete(string $search): array {
            return $this->completionSearchBackend($search)->texts();
        }
    }

    require_once __DIR__ . '/../deploy/mirklurk-search.php';

    function check(bool $condition, string $message): void {
        if (!$condition) {
            throw new RuntimeException($message);
        }
    }

    $search = new MirklurkSearch(new FakeProvider());
    $socks = $search->complete('socks');
    check($socks === ['Worn Socks', 'Decent Socks', 'Fine Wool Socks', 'Bloodsocks'],
        'Word-start matches come first, shortest first, then mid-word matches: ' . implode(', ', $socks));
    check($search->complete('SOCKS') === $socks, 'Suggestions must be case-insensitive.');
    check($search->complete('wool socks') === ['Fine Wool Socks'], 'Multi-word terms must match inside titles.');
    check($search->complete('mirkfang') === ['Mirkfang', 'Mirkfang Matriarch', 'Giant Mirkfang'],
        'Infix matches must not duplicate prefix matches.');
    $GLOBALS['queries'] = [];
    $search->complete('Help:socks');
    check($GLOBALS['queries'] === [], 'Namespaced terms keep the default prefix behaviour.');
    $search->setLimitOffset(2);
    check(count($search->complete('socks')) === 2, 'Suggestions must respect the requested limit.');
    $search->setLimitOffset(10, 10);
    $GLOBALS['queries'] = [];
    $search->complete('socks');
    check($GLOBALS['queries'] === [], 'Later pages of suggestions keep the default behaviour.');
    echo "Search suggestion tests passed.\n";
}
