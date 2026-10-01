<?php
if (!defined('MEDIAWIKI')) {
    exit;
}

use MediaWiki\MediaWikiServices;
use MediaWiki\Output\OutputPage;
use MediaWiki\Revision\RevisionRecord;
use MediaWiki\Revision\SlotRecord;
use MediaWiki\Title\Title;

/**
 * VisualEditor is available on ordinary pages. Pages whose wikitext controls what other pages
 * transclude (shared recipe, price, merchant, loot and coin data) stay source-only: VisualEditor
 * moves inclusion markers that sit between table rows on every save.
 */
final class MirklurkEditing {
    public const NOTICE = 'This page supplies shared data that other pages display, so it is edited '
        . 'with the source editor. See [[Help:Editing]].';

    /** @var array<int, bool> */
    private static array $cache = [];

    public static function requiresSourceEditing(string $wikitext): bool {
        return preg_match('/<\s*\/?\s*(?:onlyinclude|includeonly|noinclude)\b/i', $wikitext) === 1;
    }

    public static function pageRequiresSourceEditing(?Title $title): bool {
        if ($title === null || !$title->canExist() || !$title->exists()
            || $title->getContentModel() !== CONTENT_MODEL_WIKITEXT) {
            return false;
        }
        $latest = $title->getLatestRevID();
        if (!isset(self::$cache[$latest])) {
            $revision = MediaWikiServices::getInstance()->getRevisionLookup()->getRevisionById($latest);
            $content = $revision?->getContent(SlotRecord::MAIN, RevisionRecord::FOR_PUBLIC);
            // Fail closed: if the current text cannot be inspected, keep the source editor.
            self::$cache[$latest] = $content === null
                || self::requiresSourceEditing($content->serialize());
        }
        return self::$cache[$latest];
    }

    public static function onVisualEditorBeforeEditor(OutputPage $output, $skin): bool {
        if (!$skin->getUser()->isRegistered() || !self::pageRequiresSourceEditing($output->getTitle())) {
            return true;
        }
        // VisualEditor adds its section links without consulting this hook.
        $output->addInlineStyle('.mw-editsection-visualeditor,'
            . '.mw-editsection-visualeditor+.mw-editsection-divider{display:none}');
        return false;
    }

    public static function onApiCheckCanExecute($module, $user, &$message): bool {
        if ($module->getModuleName() !== 'visualeditoredit') {
            return true;
        }
        $title = Title::newFromText((string)$module->getRequest()->getVal('page', ''));
        if (!self::pageRequiresSourceEditing($title)) {
            return true;
        }
        $message = ['rawmessage', self::NOTICE];
        return false;
    }

    public static function onEditPageShowEditFormInitial($editPage, OutputPage $output): void {
        if (self::pageRequiresSourceEditing($editPage->getTitle())) {
            $output->wrapWikiTextAsInterface('mw-message-box mw-message-box-notice', self::NOTICE);
        }
    }
}
