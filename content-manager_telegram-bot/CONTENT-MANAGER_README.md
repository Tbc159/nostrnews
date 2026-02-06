rm -rf published.db
kill -9 $(ps -ef | grep nostr | grep -v grep | awk '{print$2}')
git pull
go build -o nostrnews
rm -rf nohup.out ; nohup ./nostrnews &