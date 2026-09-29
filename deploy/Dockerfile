FROM mediawiki:1.43.9@sha256:39a6503b8739f6aa58f8a458e9537258dd537f7cec7dd93c665bd3b43252d971

COPY deploy/LocalSettings.template.php /var/www/html/LocalSettings.php
COPY deploy/mirklurk-runtime.php /var/www/html/mirklurk-runtime.php
COPY deploy/install.php deploy/healthcheck.php /usr/local/lib/mirklurk/
COPY deploy/apache-short-urls.conf /etc/apache2/sites-available/000-default.conf

RUN a2enmod rewrite \
    && apache2ctl -t \
    && test -f /var/www/html/extensions/ConfirmEdit/QuestyCaptcha/extension.json \
    && test -f /var/www/html/extensions/ParserFunctions/extension.json \
    && test -f /var/www/html/extensions/Scribunto/extension.json \
    && test -f /var/www/html/extensions/VisualEditor/extension.json \
    && test -f /var/www/html/extensions/TemplateData/extension.json \
    && test -f /var/www/html/vendor/wikimedia/parsoid/extension.json \
    && test -f /var/www/html/skins/Vector/skin.json \
    && php -l /var/www/html/LocalSettings.php \
    && php -l /var/www/html/mirklurk-runtime.php \
    && php -l /usr/local/lib/mirklurk/install.php \
    && php -l /usr/local/lib/mirklurk/healthcheck.php \
    && printf 'display_errors=Off\nlog_errors=On\nexpose_php=Off\n' > /usr/local/etc/php/conf.d/mirklurk.ini

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD ["php", "/usr/local/lib/mirklurk/healthcheck.php"]
