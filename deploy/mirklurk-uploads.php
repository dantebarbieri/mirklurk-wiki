<?php
if (!defined('MEDIAWIKI')) {
    exit;
}

final class MirklurkUploads {
    public const MAX_BYTES = 10 * 1024 * 1024;
    public const MAX_PIXELS = 12000000;
    public const MAX_DIMENSION = 8192;
    public const NOTICE = "Upload PNG, JPEG or WebP images relevant to the wiki: at most 10 MiB, "
        . "12 megapixels and 8,192 pixels on either side. Prefer PNG for pixel art and diagrams. "
        . "In the summary, describe the image and identify its source, creator, permission or "
        . "license basis, and game version where relevant. Owning the game does not grant a "
        . "license to its artwork. Do not upload save files, archives or private information. "
        . "Use a descriptive filename; you can replace your own files, but an administrator "
        . "must replace someone else's. Ordinary uploaders are limited to 20 upload attempts per hour.";

    public static function onUploadVerifyFile(UploadBase $upload, $mime, &$error): bool {
        if (!in_array($mime, ['image/png', 'image/jpeg', 'image/webp'], true)) {
            $error = ['rawmessage', 'Only PNG, JPEG and WebP images may be uploaded.'];
            return false;
        }
        // Read dimensions without decoding a potentially huge compressed bitmap.
        $size = @getimagesize($upload->getTempPath());
        if ($size === false || $size[0] < 1 || $size[1] < 1 || $size['mime'] !== $mime) {
            $error = ['rawmessage', 'The image dimensions or format could not be verified. '
                . 'Export a valid PNG, JPEG or WebP image and try again.'];
            return false;
        }
        if ($size[0] > self::MAX_DIMENSION || $size[1] > self::MAX_DIMENSION
            || $size[0] * $size[1] > self::MAX_PIXELS) {
            $error = ['rawmessage', 'The image exceeds the upload limit of 12 megapixels or '
                . '8,192 pixels on either side. Crop or resize it before uploading.'];
            return false;
        }
        return true;
    }

    public static function onUploadFormInitial($uploadForm): void {
        $uploadForm->getOutput()->wrapWikiTextAsInterface('mw-message-box mw-message-box-notice', self::NOTICE);
    }
}
