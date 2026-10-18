# Worker package

- Jobs raise an exception when they fail, so the queue retries them. Never return an error value from a job: the queue treats any return as success and drops the message.
