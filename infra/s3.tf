resource "aws_s3_bucket" "query_results" {
  bucket = "${local.prefix}-query-results"
  tags   = local.tags
}

resource "aws_s3_bucket_lifecycle_configuration" "query_results_lifecycle" {
  bucket = aws_s3_bucket.query_results.id

  rule {
    id     = "expire-query-results"
    status = "Enabled"

    expiration {
      days = 7
    }
  }
}
