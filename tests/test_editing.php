<?php
define('MEDIAWIKI', true);
require_once __DIR__ . '/../deploy/mirklurk-editing.php';

foreach ([
    "Intro.\n<onlyinclude>{{#switch:x|price=1 silver|#default=}}</onlyinclude>\n",
    "{| class=\"wikitable\"\n<onlyinclude>\n|-\n| row\n</onlyinclude>\n|}",
    "Text <includeonly>shared</includeonly>",
    "Text <noinclude>[[Category:Owner]]</noinclude>",
    "</ONLYINCLUDE >",
    "< onlyinclude>",
] as $shared) {
    if (!MirklurkEditing::requiresSourceEditing($shared)) {
        throw new RuntimeException('Shared-data page left visually editable: ' . json_encode($shared));
    }
}
foreach ([
    '',
    "Ordinary prose with a [[link]] and {{Item|name=Wood Buckler}}.",
    "{| class=\"wikitable\"\n|-\n| Plain table\n|}",
    "Mentions onlyinclude in prose without a tag.",
    "<onlyincluded> is not an inclusion marker.",
] as $ordinary) {
    if (MirklurkEditing::requiresSourceEditing($ordinary)) {
        throw new RuntimeException('Ordinary page made source-only: ' . json_encode($ordinary));
    }
}
echo "Editor selection tests passed.\n";
