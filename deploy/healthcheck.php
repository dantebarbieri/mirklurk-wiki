<?php
$context = stream_context_create(['http' => [
    'timeout' => 5,
    'follow_location' => 0,
    'ignore_errors' => true,
]]);
$body = @file_get_contents(
    'http://127.0.0.1/api.php?action=query&meta=siteinfo&siprop=statistics&format=json',
    false,
    $context
);
$result = $body === false ? null : json_decode($body, true);
if (!isset($result['query']['statistics']['pages'])) {
    fwrite(STDERR, "Wiki healthcheck failed: local API or database statistics unavailable.\n");
    exit(1);
}
exit(0);
