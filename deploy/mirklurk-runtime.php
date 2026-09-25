<?php
if (PHP_SAPI !== 'cli' && !defined('MEDIAWIKI')) {
    http_response_code(404);
    exit;
}

function mirklurkEnv(string $name, ?string $default = null): string {
    $value = getenv($name);
    if ($value === false || $value === '') {
        if ($default !== null) {
            return $default;
        }
        throw new RuntimeException("Required environment setting is missing: $name");
    }
    if (preg_match('/[\x00-\x1f\x7f]/', $value)) {
        throw new RuntimeException("Environment setting contains control characters: $name");
    }
    return $value;
}

function mirklurkSecret(string $variable, int $minimum = 1): string {
    $path = mirklurkEnv($variable);
    if (!is_file($path) || !is_readable($path) || filesize($path) > 16384) {
        throw new RuntimeException("Required secret file is unavailable or too large: $variable");
    }
    $value = file_get_contents($path);
    if ($value === false) {
        throw new RuntimeException("Required secret file could not be read: $variable");
    }
    $value = rtrim($value, "\r\n");
    if (strlen($value) < $minimum || str_contains($value, "\0")) {
        throw new RuntimeException("Required secret file has an invalid value: $variable");
    }
    return $value;
}

function mirklurkServer(): string {
    $url = mirklurkEnv('MW_SERVER_URL');
    $parts = parse_url($url);
    if (
        $parts === false || !isset($parts['scheme'], $parts['host'])
        || isset($parts['user']) || isset($parts['pass']) || isset($parts['query'])
        || isset($parts['fragment']) || isset($parts['path'])
        || !in_array($parts['scheme'], ['http', 'https'], true)
        || !preg_match('/^(?:[a-zA-Z0-9.-]+|\[::1\])$/', $parts['host'])
    ) {
        throw new RuntimeException('MW_SERVER_URL must be an HTTP(S) origin without a path.');
    }
    if ($parts['scheme'] !== 'https' && !in_array($parts['host'], ['localhost', '127.0.0.1', '[::1]'], true)) {
        throw new RuntimeException('Only loopback development origins may use plain HTTP.');
    }
    return $url;
}

function mirklurkTrustedProxies(): array {
    $value = mirklurkEnv('MW_TRUSTED_PROXY_CIDRS', '');
    if ($value === '') {
        return [];
    }
    $result = [];
    foreach (explode(',', $value) as $entry) {
        $entry = trim($entry);
        $parts = explode('/', $entry);
        if (count($parts) > 2 || filter_var($parts[0], FILTER_VALIDATE_IP) === false) {
            throw new RuntimeException('MW_TRUSTED_PROXY_CIDRS contains an invalid IP or CIDR.');
        }
        $maximum = str_contains($parts[0], ':') ? 128 : 32;
        if (isset($parts[1]) && (!ctype_digit($parts[1]) || (int)$parts[1] < 1 || (int)$parts[1] > $maximum)) {
            throw new RuntimeException('MW_TRUSTED_PROXY_CIDRS contains an invalid or all-address prefix.');
        }
        $result[] = $entry;
    }
    return $result;
}

function mirklurkQuestions(): array {
    try {
        $questions = json_decode(mirklurkSecret('MW_CAPTCHA_QUESTIONS_FILE'), true, 16, JSON_THROW_ON_ERROR);
    } catch (JsonException $error) {
        throw new RuntimeException('CAPTCHA questions must be a private JSON question-to-answers object.');
    }
    if (!is_array($questions) || array_is_list($questions) || count($questions) < 1 || count($questions) > 100) {
        throw new RuntimeException('CAPTCHA requires at least one original question with an answer list.');
    }
    $safe = [];
    foreach ($questions as $question => $answers) {
        if (
            !is_string($question) || trim($question) === '' || strlen($question) > 500
            || !is_array($answers) || !array_is_list($answers) || count($answers) < 1 || count($answers) > 10
        ) {
            throw new RuntimeException('CAPTCHA question or answer-list shape is invalid.');
        }
        foreach ($answers as $answer) {
            if (!is_string($answer) || trim($answer) === '' || strlen($answer) > 200) {
                throw new RuntimeException('CAPTCHA answers must be short nonempty strings.');
            }
        }
        // QuestyCaptcha inserts its question as raw HTML.
        $safe[htmlspecialchars($question, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8')] = array_map('trim', $answers);
    }
    return $safe;
}
