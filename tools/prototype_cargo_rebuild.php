<?php
require_once __DIR__ . '/cargoRecreateData.php';

final class PrototypeCargoRebuild extends CargoRecreateData {
    public function __construct() {
        parent::__construct();
        $this->addOption('barrier', 'Pause first storage for the bounded concurrency experiment');
        $this->addOption('barrier-status', 'Read the synthetic concurrency checkpoint');
        $this->addOption('barrier-release', 'Release the synthetic concurrency checkpoint');
    }

    public function execute() {
        if ($this->hasOption('barrier-status')) {
            echo file_exists('/tmp/prototype-cargo-barrier.json')
                ? file_get_contents('/tmp/prototype-cargo-barrier.json') : '{}';
            return;
        }
        if ($this->hasOption('barrier-release')) {
            if (!touch('/tmp/prototype-cargo-release')) {
                throw new RuntimeException('Could not release the disposable barrier.');
            }
            return;
        }
        if ($this->getOption('table') !== PrototypeCargo::TABLE || $this->hasOption('replacement')) {
            throw new RuntimeException('This bounded experiment supports only its single in-place table.');
        }
        foreach (['/tmp/prototype-cargo-barrier.json', '/tmp/prototype-cargo-release'] as $path) {
            if (file_exists($path) && !unlink($path)) {
                throw new RuntimeException('Could not reset the disposable barrier.');
            }
        }
        if (!CargoUtils::getTemplateIDForDBTable(PrototypeCargo::TABLE)) {
            throw new RuntimeException('Prototype schema is not registered.');
        }
        PrototypeCargo::$pauseRebuild = $this->hasOption('barrier');
        parent::execute();
        if (!CargoUtils::tableFullyExists(PrototypeCargo::TABLE)) {
            throw new RuntimeException('Prototype rebuild did not create its complete table.');
        }
        PrototypeCargo::rebuilt();
    }
}

$maintClass = PrototypeCargoRebuild::class;
require_once RUN_MAINTENANCE_IF_MAIN;
