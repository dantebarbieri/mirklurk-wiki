<?php
define('MEDIAWIKI', true);
require_once __DIR__ . '/../deploy/mirklurk-metadata.php';

function descriptionIs(string $html, string $expected): void {
    $actual = MirklurkMetadata::description('<div class="mw-parser-output">' . $html . '</div>');
    if ($actual !== $expected || mb_strlen($actual, 'UTF-8') > 240) {
        throw new RuntimeException('Description mismatch: ' . json_encode([$actual, $expected]));
    }
}

descriptionIs('<p>Browse <b>equipment</b>, <a href="/x">materials</a> and supplies.</p>',
    'Browse equipment, materials and supplies.');
descriptionIs('<p>A &amp; B &quot;quoted&quot; &#233;lan &#x1F331;.</p>', "A & B \"quoted\" \u{e9}lan \u{1f331}.");
descriptionIs("<p> One\n two&nbsp; three. </p>", 'One two three.');
descriptionIs('<table><tr><td><p>Not the infobox.</p></td></tr></table><p>The lead.</p>', 'The lead.');
descriptionIs('<p><img src="/x" alt="Caption"></p><p>The lead.</p>', 'The lead.');
descriptionIs('<p>Claim <sup class="unverified">Unverified</sup></p><p>A useful lead.</p>', 'A useful lead.');
descriptionIs('<p hidden>Secret.</p><p style="display:none">Secret.</p><p>The lead.</p>', 'The lead.');
descriptionIs('<p>A <span style="display:none">secret</span> claim.</p><p>The lead.</p>', 'The lead.');
descriptionIs('<p>Research status: initializer records.</p><p>Browse equipment.</p>', 'Browse equipment.');
descriptionIs('<p>{{Template}} [[Raw link]]</p><p>The lead.</p>', 'The lead.');
descriptionIs('<p>&lt;script&gt;alert(1)&lt;/script&gt;</p>', '');
descriptionIs('<p>Spoilers: future events.</p><h2>Story</h2><p>Do not extract this.</p>', '');
descriptionIs('<div class="mw-heading mw-heading2"><h2>Stats</h2></div><p>Later.</p>', '');
descriptionIs('<p>' . str_repeat('word ', 55) . '</p>', '');
descriptionIs('<p>A complete sentence. ' . str_repeat('long ', 55) . '</p>', 'A complete sentence.');
descriptionIs('<p>' . str_repeat("\u{e9}", 238) . '.</p>', str_repeat("\u{e9}", 238) . '.');
descriptionIs('<p>' . str_repeat("\u{e9}", 240) . '.</p>', '');
descriptionIs('<p>' . str_repeat("\u{e9}", 239) . '. Next sentence.</p>', str_repeat("\u{e9}", 239) . '.');
descriptionIs('<p>Pending rights, missing artwork.</p>', '');
// Entity pages lead with a breadcrumb, the bold name label and guide links before any prose.
descriptionIs('<p><a href="/w/Main_Page">Main Page</a> | <a href="/w/Items">Items</a></p>'
    . '<p><span id="entity-item-142"></span><b>Calmia Root</b> <span id="x"></span></p>'
    . '<p><a href="/w/Plant_harvesting">Related acquisition guide</a></p>', '');
descriptionIs('<p><a href="/w/Main_Page">Main Page</a> | <a href="/w/Items">Items</a></p>'
    . '<p><b>Sceetler</b></p><p>A <a href="/w/Swamp">swamp</a> insect that flees when hit.</p>',
    'A swamp insect that flees when hit.');
descriptionIs('<p><b>Calmia Root</b> is a medicinal root.</p>', 'Calmia Root is a medicinal root.');
descriptionIs('<p><a href="/w/Main_Page">Main Page</a> | <a href="/w/Items">Items</a></p>'
    . '<p><span id="entity-item-142"></span><b>Calmia Root</b>: a crafting material that can be collected.'
    . "\n" . '<span id="illustration-item-142-illustration"></span></p>',
    'Calmia Root: a crafting material that can be collected.');
foreach ([[[128, 128], 8], [[80, 240], 4], [[1024, 512], 1], [[2000, 10], 1], [[0, 5], 1], [[171, 228], 4]]
         as [[$width, $height], $scale]) {
    if (MirklurkMetadata::previewScale($width, $height) !== $scale) {
        throw new RuntimeException("Preview scale for {$width}x{$height} is not {$scale}.");
    }
}
if (MirklurkMetadata::description('<p>Outside article.</p>') !== '') {
    throw new RuntimeException('Nonarticle HTML must not become a description.');
}
echo "Rendered description tests passed.\n";
