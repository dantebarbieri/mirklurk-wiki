<?php
declare(strict_types=1);

if (PHP_SAPI !== 'cli' || getenv('NATIVE_DISPOSABLE_FIXTURE') !== '1') {
    exit(1);
}
require_once dirname(__DIR__) . '/tools/native_publication.php';

class DisposableNativePublication extends NativePublication {
    public function __construct() {
        parent::__construct();
        $this->addOption('fixture-stage', 'Pause at one synthetic boundary', true, true);
    }

    protected function checkpoint(string $stage): void {
        if ($stage === $this->getOption('fixture-stage')) {
            $this->output(json_encode(['fixture_checkpoint' => $stage], JSON_THROW_ON_ERROR) . "\n");
            flush();
            $deadline = microtime(true) + 90;
            while (!is_file('/tmp/native-fixture-release')) {
                if (microtime(true) > $deadline) {
                    throw new RuntimeException('fixture-release-timeout');
                }
                usleep(50000);
            }
        }
    }
}

$maintClass = DisposableNativePublication::class;
require RUN_MAINTENANCE_IF_MAIN;
