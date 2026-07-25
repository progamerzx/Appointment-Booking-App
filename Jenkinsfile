pipeline{
    agent any
        environment{
            IMAGE_NAME = "ctslab/abp"
            IMAGE_TAG = "${BUILD_NUMBER}"
        }
        stages{

            stage('checkout'){
                steps{
                    checkout scm
                }
            }

            stage('Build the docker image'){
                steps{
                    bat "docker build -t ${IMAGE_NAME}:${IMAGE_TAG} ."
                }
            }

            stage('Verify Docker Image'){
                steps{
                    bat "docker image inspect ${IMAGE_NAME}:${IMAGE_TAG}"
                }
            }

            stage('Login to docker registry'){
                steps{
                    withCredentials([
                        usernamePassword(
                        credentialsId:'dockerhub-creds',
                        usernameVariable:'DOCKER_USER',
                        passwordVariable:'DOCKER_PASS'
                    )
                ]){
                    bat "docker login -u %DOCKER_USER% -p %DOCKER_PASS%"
                }
                }
            }

            stage('Push Image to docker registry'){
                steps{
                    bat "docker push ${IMAGE_NAME}:${IMAGE_TAG}"
                    bat "docker logout"
                }
            }

            stage('Verify docker hub push'){
                steps{
                    bat "docker pull ${IMAGE_NAME}:${IMAGE_TAG}"    
                }
            }
        }

        post{
            success {
                echo 'Pipeline Executed Successfully'
            }

            failure {
                echo 'Pipeline Failed'
            }
        }
}
