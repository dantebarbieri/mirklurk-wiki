<?php
if (!defined('MEDIAWIKI')) {
    exit;
}

use MediaWiki\Html\Html;
use MediaWiki\MediaWikiServices;
use MediaWiki\Output\OutputPage;
use MediaWiki\Search\Entity\SearchResultThumbnail;
use MediaWiki\Title\Title;
use PageImages\PageImages;

final class MirklurkMetadata {
    public static function description(string $html): string {
        $document = new DOMDocument();
        // Parser output is an HTML fragment, not XML. Never resolve external entities.
        $previous = libxml_use_internal_errors(true);
        try {
            $loaded = $document->loadHTML(
                '<?xml encoding="UTF-8"><html><body>' . $html . '</body></html>',
                LIBXML_NONET
            );
        } finally {
            libxml_clear_errors();
            libxml_use_internal_errors($previous);
        }
        if (!$loaded) {
            throw new RuntimeException('Unable to read rendered article metadata.');
        }
        $xpath = new DOMXPath($document);
        $roots = $xpath->query('//*[contains(concat(" ", normalize-space(@class), " "), " mw-parser-output ")]');
        if ($roots->length !== 1) {
            return '';
        }
        foreach ($roots->item(0)->childNodes as $node) {
            if (!$node instanceof DOMElement) {
                continue;
            }
            if (preg_match('/^h[1-6]$/', $node->tagName)
                || in_array('mw-heading', explode(' ', $node->getAttribute('class')), true)) {
                break;
            }
            // Only a visible lead paragraph, never infoboxes, nav, captions or later sections.
            if ($node->tagName !== 'p' || $xpath->query(
                './/*[@hidden or @style or @aria-hidden="true" or self::sup or self::img'
                . ' or contains(@class, "unverified") or contains(@class, "error")]'
                . ' | self::*[@hidden or @style or @aria-hidden="true"]', $node
            )->length) {
                continue;
            }
            $text = trim(preg_replace('/[\s\p{Z}]+/u', ' ', $node->textContent));
            if ($text === '' || preg_match(
                '/\{\{|\}\}|\[\[|\]\]|__\w+__|<[^>]+>|\b(?:spoilers?|unverified|'
                . 'not documented|unknown|initializer|provenance|editorial|'
                . 'research (?:status|notes|policy|records)|source (?:records|files|paths)|'
                . 'runtime.verified|verification|pending rights)\b/iu', $text
            )) {
                continue;
            }
            // Use whole sentences. Never cut a word, code point, or a trailing qualification.
            if (mb_strlen($text, 'UTF-8') <= 240) {
                return $text;
            }
            preg_match('/^.{1,239}[.!?](?=\s|$)/u', $text, $sentence);
            if ($sentence && mb_strlen($sentence[0], 'UTF-8') <= 240) {
                return $sentence[0];
            }
        }
        return '';
    }

    public static function onHeadLinks(array &$tags, OutputPage $out): void {
        $title = $out->getTitle();
        $services = MediaWikiServices::getInstance();
        $permissions = $services->getPermissionManager();
        $public = $title && !$title->isSpecialPage() && $title->exists()
            && $permissions->isEveryoneAllowed('read')
            && $permissions->userCan('read', $services->getUserFactory()->newAnonymous(), $title);
        // Core's nonarticle fallback uses the request URL, including arbitrary query values.
        if (!$public || !$out->isArticleRelated()) {
            unset($tags['link-canonical']);
            return;
        }
        $request = $out->getRequest();
        if (!$out->isArticle() || $out->getContext()->getActionName() !== 'view'
            || $request->wasPosted() || $request->getCheck('oldid') || $request->getCheck('diff')
            || $request->getCheck('veaction') || $out->getUser()->isRegistered()
            || !str_starts_with($out->getRobotPolicy(), 'index,')
            || !in_array($title->getNamespace(), [NS_MAIN, NS_CATEGORY], true)
            || $title->isRedirect() || $title->getContentModel() !== CONTENT_MODEL_WIKITEXT) {
            return;
        }
        // Reuse the actual core canonical, including redirect/variant handling.
        $canonical = new DOMDocument();
        if (!isset($tags['link-canonical'])
            || !$canonical->loadHTML($tags['link-canonical'], LIBXML_NONET)) {
            return;
        }
        $url = $canonical->getElementsByTagName('link')->item(0)->getAttribute('href');
        $description = self::description($out->getHTML());
        $values = [
            'og:type' => $title->isMainPage() ? 'website' : 'article',
            'og:site_name' => $out->getConfig()->get('Sitename'),
            'og:title' => $title->getPrefixedText(),
            'og:url' => $url,
        ];
        if ($description !== '') {
            $tags['mirklurk-description'] = Html::element('meta', [
                'name' => 'description', 'content' => $description,
            ]);
            $values['og:description'] = $description;
        }
        // The page's own reviewed lead figure, else the explicit, rights-approved site icon.
        $file = self::pageImage($title);
        $image = $file ? $file->getFullUrl() : mirklurkImageUrl('MW_LOGO_ICON_URL');
        if ($image !== '') {
            $values['og:image'] = $services->getUrlUtils()->expand($image, PROTO_CANONICAL);
            $values['og:image:alt'] = $file ? $title->getPrefixedText() : $out->getConfig()->get('Sitename');
        }
        foreach ($values as $property => $value) {
            $tags['mirklurk-' . $property] = Html::element('meta', [
                'property' => $property, 'content' => $value,
            ]);
        }
        $tags['mirklurk-card'] = Html::element('meta', ['name' => 'twitter:card', 'content' => 'summary']);
    }

    /** PageImages' choice: only lead figures, because inline icons are class=notpageimage. */
    private static function pageImage(Title $title): ?File {
        if (!class_exists(PageImages::class)) {
            return null;
        }
        $file = PageImages::getPageImage($title);
        return $file && $file->exists() && str_starts_with($file->getMimeType(), 'image/') ? $file : null;
    }

    /**
     * Search results show the original pixel art, never an interpolated ImageMagick thumbnail.
     * Registered after extensions load, so this runs after PageImages has chosen the file.
     */
    public static function onSearchResultProvideThumbnail(array $pages, array &$results, ?int $size = null): void {
        $services = MediaWikiServices::getInstance();
        $repos = $services->getRepoGroup();
        foreach ($results as $id => $thumbnail) {
            if (!$thumbnail instanceof SearchResultThumbnail || $thumbnail->getName() === null) {
                continue;
            }
            $file = $repos->findFile($thumbnail->getName());
            if (!$file || !$file->exists() || !$file->getWidth() || !$file->getHeight()) {
                continue;
            }
            $results[$id] = new SearchResultThumbnail(
                $file->getMimeType(),
                $file->getSize(),
                $file->getWidth(),
                $file->getHeight(),
                null,
                $services->getUrlUtils()->expand($file->getFullUrl(), PROTO_RELATIVE),
                $file->getName()
            );
        }
    }

    public static function onBeforePageDisplay(OutputPage $out): void {
        // Scale search thumbnails (typeahead and Special:Search) without blur or cropping.
        $out->addInlineStyle(
            '.cdx-thumbnail__image,.cdx-menu-item__thumbnail,.searchResultImage-thumbnail img'
            . '{image-rendering:pixelated;background-size:contain;background-repeat:no-repeat;'
            . 'object-fit:contain;object-position:center}'
        );
    }
}
