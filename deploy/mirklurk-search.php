<?php
if (!defined('MEDIAWIKI')) {
    http_response_code(404);
    exit;
}

use MediaWiki\Title\Title;

/**
 * Search-box suggestions that also match words inside titles.
 *
 * The default suggester only matches the start of a title, so "socks" found nothing
 * although Worn Socks, Decent Socks and Fine Wool Socks exist. Prefix matches still
 * come first; case-insensitive matches elsewhere in the title fill the remaining
 * slots, with matches at the start of a word ranked before mid-word matches.
 */
final class MirklurkSearch extends SearchMySQL {
    private const MAX_TERM_LENGTH = 100;
    private const CANDIDATES = 200;

    protected function completionSearchBackend($search) {
        $suggestions = parent::completionSearchBackend($search);
        $term = trim(preg_replace('/[\s_]+/u', ' ', (string)$search));
        if ($term === '' || mb_strlen($term) > self::MAX_TERM_LENGTH || $suggestions->getSize() >= $this->limit
            || $this->offset > 0 || str_contains($term, ':')) {
            return $suggestions;
        }
        $titles = array_slice(self::rank($term, $this->infixCandidates($term)), 0, 2 * $this->limit);
        $merged = new SearchSuggestionSet($suggestions->getSuggestions(), $suggestions->hasMoreResults());
        $more = SearchSuggestionSet::fromTitles($titles);
        foreach ($more->getSuggestions() as $suggestion) {
            if ($merged->getSize() >= $this->limit) {
                break;
            }
            $merged->append($suggestion);
        }
        return $merged;
    }

    private function infixCandidates(string $term): array {
        $namespaces = array_values(array_unique(array_map('intval', $this->namespaces ?: [NS_MAIN])));
        if ($namespaces === []) {
            return [];
        }
        $db = $this->dbProvider->getReplicaDatabase();
        $needle = mb_strtolower(str_replace(' ', '_', $term));
        $rows = $db->newSelectQueryBuilder()
            ->select(['page_namespace', 'page_title'])
            ->from('page')
            ->where([
                'page_namespace' => $namespaces,
                'page_is_redirect' => 0,
                'LOWER(CONVERT(page_title USING utf8mb4)) '
                    . $db->buildLike($db->anyString(), $needle, $db->anyString()),
            ])
            ->limit(self::CANDIDATES)
            ->caller(__METHOD__)
            ->fetchResultSet();
        $titles = [];
        foreach ($rows as $row) {
            $titles[] = Title::makeTitle((int)$row->page_namespace, $row->page_title);
        }
        return $titles;
    }

    /** Word-start matches first, then shorter titles, then alphabetical. */
    public static function rank(string $term, array $titles): array {
        $needle = mb_strtolower($term);
        $keyed = [];
        foreach ($titles as $title) {
            $text = mb_strtolower($title->getText());
            $position = mb_strpos($text, $needle);
            if ($position === false) {
                continue;
            }
            $wordStart = $position === 0 || preg_match('/[\s\-\'(]/u', mb_substr($text, $position - 1, 1));
            $keyed[] = [$wordStart ? 0 : 1, mb_strlen($text), $text, $title];
        }
        usort($keyed, static fn(array $a, array $b): int => [$a[0], $a[1], $a[2]] <=> [$b[0], $b[1], $b[2]]);
        return array_column($keyed, 3);
    }
}
