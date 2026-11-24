FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APACHE_RUN_DIR=/var/run/apache2 \
    APACHE_LOCK_DIR=/var/lock/apache2 \
    APACHE_LOG_DIR=/var/log/apache2

RUN apt-get update && apt-get install -y --no-install-recommends \
      apache2 apache2-dev gcc libc6-dev ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir mod_wsgi \
    && mod_wsgi-express module-config > /etc/apache2/mod_wsgi.conf \
    && printf "\nInclude /etc/apache2/mod_wsgi.conf\n" >> /etc/apache2/apache2.conf \
    && a2enmod headers

COPY . /app
RUN mkdir -p /app/uploads \
    && chown -R www-data:www-data /app/uploads \
    && a2dissite 000-default

COPY apache/video-service.conf /etc/apache2/sites-available/video-service.conf
RUN a2ensite video-service

EXPOSE 80
CMD ["/bin/sh", "-c", "apachectl -t && apachectl -D FOREGROUND"]
