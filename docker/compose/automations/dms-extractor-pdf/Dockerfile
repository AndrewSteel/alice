FROM node:20-alpine

WORKDIR /app

COPY package.json .
RUN npm install --production

COPY main.js .

CMD ["node", "main.js"]
