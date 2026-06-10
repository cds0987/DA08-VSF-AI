import net from 'node:net'

const port = Number(process.argv[2])

if (!Number.isInteger(port) || port <= 0) {
  console.error('Usage: node scripts/assert-port-free.mjs <port>')
  process.exit(1)
}

const server = net.createServer()

server.once('error', (error) => {
  if (error.code === 'EADDRINUSE') {
    console.error(`Port ${port} is already in use. Stop the process on that port before starting this app.`)
    process.exit(1)
  }

  console.error(error.message)
  process.exit(1)
})

server.once('listening', () => {
  server.close(() => process.exit(0))
})

server.listen(port, '127.0.0.1')
