<?php
define('MEDIAWIKI', true);
require_once __DIR__ . '/../deploy/mirklurk-uploads.php';

class UploadBase {
    public function __construct(private string $path) {
    }
    public function getTempPath(): string {
        return $this->path;
    }
}

function png(int $width, int $height): string {
    $chunk = static function (string $type, string $data): string {
        return pack('N', strlen($data)) . $type . $data . pack('N', crc32($type . $data));
    };
    return "\x89PNG\r\n\x1a\n"
        . $chunk('IHDR', pack('NNCCCCC', $width, $height, 8, 2, 0, 0, 0))
        . $chunk('IDAT', gzcompress(str_repeat("\0" . str_repeat("\x10\x20\x30", $width), $height)))
        . $chunk('IEND', '');
}

$path = tempnam(sys_get_temp_dir(), 'mirklurk-upload-');
try {
    foreach ([
        [1, 1, true], [3840, 2160, true], [4000, 3000, true],
        [8192, 1, true], [1, 8192, true],
        [4001, 3000, false], [3000, 4001, false],
        [8193, 1, false], [1, 8193, false],
    ] as [$width, $height, $allowed]) {
        file_put_contents($path, png($width, $height));
        $error = true;
        $result = MirklurkUploads::onUploadVerifyFile(new UploadBase($path), 'image/png', $error);
        if ($result !== $allowed || ($error === true) !== $allowed) {
            throw new RuntimeException("Incorrect dimension boundary: $width x $height.");
        }
        if (!$allowed && (!is_array($error) || !str_contains($error[1], '12 megapixels'))) {
            throw new RuntimeException('Oversized images need an actionable user-facing error.');
        }
    }
    foreach ([
        ['invalid image', 'image/png'],
        [png(1, 1), 'image/jpeg'],
        [png(1, 1), 'image/webp'],
        [png(1, 1), 'image/svg+xml'],
        [png(1, 1), null],
    ] as [$bytes, $mime]) {
        file_put_contents($path, $bytes);
        $error = true;
        if (MirklurkUploads::onUploadVerifyFile(new UploadBase($path), $mime, $error)
            || !is_array($error) || $error[0] !== 'rawmessage') {
            throw new RuntimeException('Invalid image must fail with an explicit error.');
        }
    }
    unlink($path);
    $error = true;
    if (MirklurkUploads::onUploadVerifyFile(new UploadBase($path), 'image/png', $error) || !is_array($error)) {
        throw new RuntimeException('Missing image must fail explicitly.');
    }
    echo "Upload dimension and format tests passed.\n";
} finally {
    if (is_file($path)) {
        unlink($path);
    }
}
